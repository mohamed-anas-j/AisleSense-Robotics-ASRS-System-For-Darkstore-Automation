"""
AisleSense Region Navigator — Navigation Client
================================================
Sends ``NavigateToPose`` goals to the Nav2 stack and publishes initial
pose estimates.  The client attempts to use ``rclpy`` first (requires a
sourced ROS 2 environment); falls back to the ``ros2`` CLI via subprocess;
and finally prints a dry-run summary if neither backend is available.
"""
import math
import os
import subprocess
import threading


def yaw_to_quaternion(yaw: float):
    """Convert yaw (rad) → [qx, qy, qz, qw]."""
    return [0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)]


class Navigator:
    """Sends goal poses and initial-pose estimates to the Nav2 stack."""

    def __init__(self, domain_id: int = 42):
        self.domain_id = domain_id
        self._use_rclpy = False
        self._node = None
        self._action_client = None
        self._initial_pose_pub = None
        self._cancel_scan = threading.Event()
        self._scan_thread: threading.Thread | None = None
        self._init_ros()

    # ROS 2 initialisation -------------------------------------------------
    def _init_ros(self):
        try:
            import rclpy
            from rclpy.node import Node
            from rclpy.action import ActionClient
            from nav2_msgs.action import NavigateToPose
            from geometry_msgs.msg import PoseWithCovarianceStamped

            os.environ['ROS_DOMAIN_ID'] = str(self.domain_id)
            if not rclpy.ok():
                rclpy.init()

            self._node = Node('aislesense_navigator')
            self._action_client = ActionClient(
                self._node, NavigateToPose, 'navigate_to_pose')

            # Publisher for /initialpose (2D Pose Estimate)
            self._initial_pose_pub = self._node.create_publisher(
                PoseWithCovarianceStamped, '/initialpose', 10)

            self._use_rclpy = True

            # Spin in a daemon thread so callbacks fire
            threading.Thread(target=rclpy.spin,
                             args=(self._node,), daemon=True).start()
            print("[Navigator] rclpy action client ready")
        except Exception as exc:
            print(f"[Navigator] rclpy unavailable ({exc}); "
                  "will try ros2 CLI fallback")
            self._use_rclpy = False

    # Initial Pose (2D Pose Estimate) --------------------------------------
    def set_initial_pose(self, x: float, y: float, yaw: float,
                         callback=None):
        """
        Publish an initial pose estimate on ``/initialpose``
        (equivalent to the *2D Pose Estimate* button in RViz).
        """
        quat = yaw_to_quaternion(yaw)
        if self._use_rclpy:
            self._initial_pose_rclpy(x, y, quat, callback)
        else:
            self._initial_pose_subprocess(x, y, quat, callback)

    def _initial_pose_rclpy(self, x, y, q, callback):
        from geometry_msgs.msg import PoseWithCovarianceStamped
        import time

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.pose.position.x = float(x)
        msg.pose.pose.position.y = float(y)
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation.x = q[0]
        msg.pose.pose.orientation.y = q[1]
        msg.pose.pose.orientation.z = q[2]
        msg.pose.pose.orientation.w = q[3]
        # Covariance — small default values (diagonal)
        cov = [0.0] * 36
        cov[0] = 0.25   # x
        cov[7] = 0.25   # y
        cov[35] = 0.06853891945200942  # yaw
        msg.pose.covariance = cov

        # Publish a few times to make sure AMCL picks it up
        def _pub():
            for _ in range(5):
                self._initial_pose_pub.publish(msg)
                time.sleep(0.1)
            if callback:
                callback(True, "Initial pose set via rclpy")

        threading.Thread(target=_pub, daemon=True).start()

    def _initial_pose_subprocess(self, x, y, q, callback):
        env = os.environ.copy()
        env['ROS_DOMAIN_ID'] = str(self.domain_id)

        yaml_msg = (
            f"\"{{header: {{frame_id: 'map'}}, "
            f"pose: {{pose: {{position: {{x: {x}, y: {y}, z: 0.0}}, "
            f"orientation: {{x: {q[0]}, y: {q[1]}, "
            f"z: {q[2]}, w: {q[3]}}}}}, "
            f"covariance: [0.25, 0,0,0,0,0, "
            f"0, 0.25, 0,0,0,0, "
            f"0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, "
            f"0,0,0,0,0, 0.06853891945200942]}}}}\""
        )
        cmd = (f"ros2 topic pub --once /initialpose "
               f"geometry_msgs/msg/PoseWithCovarianceStamped {yaml_msg}")

        def _run():
            try:
                result = subprocess.run(
                    cmd, shell=True, env=env,
                    capture_output=True, text=True, timeout=15)
                if callback:
                    if result.returncode == 0:
                        callback(True, "Initial pose published via ros2 CLI")
                    else:
                        callback(False,
                                 f"ros2 CLI error: {result.stderr.strip()}")
            except FileNotFoundError:
                if callback:
                    callback(False,
                             "ros2 CLI not found — source ROS 2 first")
            except subprocess.TimeoutExpired:
                if callback:
                    callback(False, "ros2 pub timed out")
            except Exception as exc:
                if callback:
                    callback(False, str(exc))

        threading.Thread(target=_run, daemon=True).start()

    # Public API ------------------------------------------------------------
    def navigate_to(self, x: float, y: float, yaw: float, callback=None):
        """
        Send a goal pose.  *callback(success: bool, message: str)*
        is called from a background thread when the result arrives.
        """
        quat = yaw_to_quaternion(yaw)
        if self._use_rclpy:
            self._nav_rclpy(x, y, quat, callback)
        else:
            self._nav_subprocess(x, y, quat, callback)

    # Scan Tour ----------------------------------------------------------------
    def run_scan_tour(self, waypoints, wait_seconds=2, progress_cb=None,
                      done_cb=None):
        """
        Navigate sequentially through *waypoints* —
        a list of ``(name, x, y, yaw)`` tuples.
        Calls *progress_cb(index, name, status, message)* on updates.
        Calls *done_cb(success, message)* when the tour ends.
        """
        self._cancel_scan.clear()

        def _tour():
            total = len(waypoints)
            for i, (name, x, y, yaw) in enumerate(waypoints):
                if self._cancel_scan.is_set():
                    if done_cb:
                        done_cb(False, "Scan cancelled")
                    return
                if progress_cb:
                    progress_cb(i, name, "navigating",
                                f"[{i+1}/{total}] Navigating to '{name}'…")

                # Blocking navigate
                event = threading.Event()
                result_box = [False, ""]

                def _cb(ok, msg, _e=event, _r=result_box):
                    _r[0] = ok
                    _r[1] = msg
                    _e.set()

                self.navigate_to(x, y, yaw, callback=_cb)
                # Wait for navigation (up to 5 min per waypoint)
                event.wait(timeout=300)

                if self._cancel_scan.is_set():
                    if done_cb:
                        done_cb(False, "Scan cancelled")
                    return

                if not result_box[0]:
                    if progress_cb:
                        progress_cb(i, name, "failed", result_box[1])
                    if done_cb:
                        done_cb(False,
                                f"Failed at '{name}': {result_box[1]}")
                    return

                # Arrived — wait at the region
                if progress_cb:
                    progress_cb(i, name, "waiting",
                                f"[{i+1}/{total}] At '{name}' — "
                                f"waiting {wait_seconds}s…")
                for _ in range(wait_seconds * 10):
                    if self._cancel_scan.is_set():
                        if done_cb:
                            done_cb(False, "Scan cancelled")
                        return
                    threading.Event().wait(0.1)

                if progress_cb:
                    progress_cb(i, name, "done",
                                f"[{i+1}/{total}] '{name}' ✓")

            if done_cb:
                done_cb(True, "Scan tour complete!")

        self._scan_thread = threading.Thread(target=_tour, daemon=True)
        self._scan_thread.start()

    def cancel_scan(self):
        """Signal the running scan tour to stop."""
        self._cancel_scan.set()

    @property
    def scanning(self) -> bool:
        return (self._scan_thread is not None
                and self._scan_thread.is_alive())

    # rclpy backend -----------------------------------------------------------
    def _nav_rclpy(self, x, y, q, callback):
        from nav2_msgs.action import NavigateToPose
        from geometry_msgs.msg import PoseStamped

        if not self._action_client.wait_for_server(timeout_sec=5.0):
            if callback:
                callback(False, "Nav2 action server not available (timeout)")
            return

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        goal.pose.pose.position.z = 0.0
        goal.pose.pose.orientation.x = q[0]
        goal.pose.pose.orientation.y = q[1]
        goal.pose.pose.orientation.z = q[2]
        goal.pose.pose.orientation.w = q[3]

        future = self._action_client.send_goal_async(goal)
        future.add_done_callback(lambda f: self._on_response(f, callback))

    def _on_response(self, future, callback):
        gh = future.result()
        if not gh.accepted:
            if callback:
                callback(False, "Goal rejected by Nav2")
            return
        result_future = gh.get_result_async()
        result_future.add_done_callback(lambda f: self._on_result(f, callback))

    @staticmethod
    def _on_result(future, callback):
        if callback:
            callback(True, "Navigation complete!")

    # Subprocess (ros2 CLI) backend ----------------------------------------
    def _nav_subprocess(self, x, y, q, callback):
        env = os.environ.copy()
        env['ROS_DOMAIN_ID'] = str(self.domain_id)

        yaml_msg = (
            f"\"{{header: {{frame_id: 'map'}}, "
            f"pose: {{position: {{x: {x}, y: {y}, z: 0.0}}, "
            f"orientation: {{x: {q[0]}, y: {q[1]}, "
            f"z: {q[2]}, w: {q[3]}}}}}}}\""
        )
        cmd = (f"ros2 topic pub --once /goal_pose "
               f"geometry_msgs/msg/PoseStamped {yaml_msg}")

        def _run():
            try:
                result = subprocess.run(
                    cmd, shell=True, env=env,
                    capture_output=True, text=True, timeout=15)
                if callback:
                    if result.returncode == 0:
                        callback(True, "Goal published via ros2 CLI")
                    else:
                        callback(False,
                                 f"ros2 CLI error: {result.stderr.strip()}")
            except FileNotFoundError:
                if callback:
                    callback(False,
                             "ros2 CLI not found — source ROS 2 first")
            except subprocess.TimeoutExpired:
                if callback:
                    callback(False, "ros2 pub timed out")
            except Exception as exc:
                if callback:
                    callback(False, str(exc))

        threading.Thread(target=_run, daemon=True).start()

    # Cleanup ------------------------------------------------------------------
    def shutdown(self):
        self._cancel_scan.set()
        if self._use_rclpy and self._node:
            self._node.destroy_node()
            try:
                import rclpy
                rclpy.shutdown()
            except Exception:
                pass
