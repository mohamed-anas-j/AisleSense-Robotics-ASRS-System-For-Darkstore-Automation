#!/usr/bin/env python3
"""
Waypoint Collector Node — click goals in RViz2, they queue up,
then publish to /start_waypoints to send them all at once.

Usage from your laptop:
  1. In RViz2, click "2D Goal Pose" to add waypoints (robot won't move)
  2. When ready:  ros2 topic pub --once /start_waypoints std_msgs/Empty
  3. To clear:    ros2 topic pub --once /clear_waypoints std_msgs/Empty

The node intercepts /goal_pose (RViz2's output) and prevents Nav2
from receiving it by using the FollowWaypoints action instead of
NavigateToPose.
"""
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import Empty
from nav2_msgs.action import FollowWaypoints


class WaypointCollector(Node):
    def __init__(self):
        super().__init__('waypoint_collector')

        self.waypoints = []
        self.following = False

        # Intercept goal_pose from RViz2 (this is what "2D Goal Pose" publishes)
        self.create_subscription(PoseStamped, '/goal_pose', self.goal_cb, 10)

        # Control topics
        self.create_subscription(Empty, '/start_waypoints', self.start_cb, 10)
        self.create_subscription(Empty, '/clear_waypoints', self.clear_cb, 10)

        # Nav2 FollowWaypoints action client
        self.follow_client = ActionClient(self, FollowWaypoints, 'follow_waypoints')

        self.get_logger().info(
            'Waypoint Collector ready — click "2D Goal Pose" to queue waypoints, '
            'then: ros2 topic pub --once /start_waypoints std_msgs/Empty')

    def goal_cb(self, msg: PoseStamped):
        """Queue a waypoint instead of navigating immediately."""
        if self.following:
            self.get_logger().warn('Currently following waypoints — ignoring new goal. Clear first.')
            return

        self.waypoints.append(msg)
        n = len(self.waypoints)
        pos = msg.pose.position
        self.get_logger().info(
            f'Waypoint #{n} added: ({pos.x:.2f}, {pos.y:.2f}) — '
            f'{n} total queued. Publish /start_waypoints to go!')

    def clear_cb(self, msg: Empty):
        """Clear all queued waypoints."""
        count = len(self.waypoints)
        self.waypoints.clear()
        self.following = False
        self.get_logger().info(f'Cleared {count} waypoints.')

    def start_cb(self, msg: Empty):
        """Send all queued waypoints to Nav2 FollowWaypoints."""
        if not self.waypoints:
            self.get_logger().warn('No waypoints queued! Click "2D Goal Pose" first.')
            return

        if self.following:
            self.get_logger().warn('Already following waypoints. Clear and re-queue to restart.')
            return

        self.get_logger().info(f'Starting waypoint following with {len(self.waypoints)} waypoints...')

        if not self.follow_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('FollowWaypoints action server not available!')
            return

        goal = FollowWaypoints.Goal()
        goal.poses = list(self.waypoints)

        self.following = True
        future = self.follow_client.send_goal_async(
            goal, feedback_callback=self.feedback_cb)
        future.add_done_callback(self.goal_response_cb)

    def goal_response_cb(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('FollowWaypoints goal rejected!')
            self.following = False
            return

        self.get_logger().info('FollowWaypoints accepted — robot is moving!')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.result_cb)

    def feedback_cb(self, feedback_msg):
        current = feedback_msg.feedback.current_waypoint
        total = len(self.waypoints)
        self.get_logger().info(f'Heading to waypoint {current + 1}/{total}')

    def result_cb(self, future):
        result = future.result().result
        missed = result.missed_waypoints
        if missed:
            self.get_logger().warn(f'Done! Missed waypoints: {list(missed)}')
        else:
            self.get_logger().info('All waypoints reached successfully!')
        self.waypoints.clear()
        self.following = False


def main(args=None):
    rclpy.init(args=args)
    node = WaypointCollector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
