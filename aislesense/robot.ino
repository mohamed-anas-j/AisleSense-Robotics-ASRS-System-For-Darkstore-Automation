#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <avr/wdt.h> // Watchdog library for "Insta-Reset"

Adafruit_MPU6050 mpu;

// Encoder Pins 
volatile long left_ticks = 0;
volatile long right_ticks = 0;
const int PIN_L_A = 2; const int PIN_L_B = 3;
const int PIN_R_A = 18; const int PIN_R_B = 19;

// L298N Motor Driver Pins
const int IN1 = 4; const int IN2 = 5;
const int IN3 = 6; const int IN4 = 7;

// Limit Switch Pin
const int LIMIT_SWITCH = 8; 

// Tray State Tracking
bool movingIn = false;
bool movingOut = false;

// Timers
unsigned long previousMillis = 0;
const long interval = 20; // 50Hz update rate
unsigned long moveOutStartTime = 0;
const unsigned long OUT_DURATION = 500; // 0.5 Seconds

// Calibration Offsets
float gx_offset = 0, gy_offset = 0, gz_offset = 0;
float ax_offset = 0, ay_offset = 0, az_offset = 0;

void setup() {
  Serial.begin(115200);
  
  // 1. WATCHDOG: Reset the Arduino if it freezes for more than 2 seconds
  wdt_enable(WDTO_2S); 

  // 2. I2C TIMEOUT: Stop the IMU from locking up the loop
  Wire.begin();
  Wire.setWireTimeout(3000, true); 

  Serial.println("\n--- SYSTEM BOOT / RESET ---");

  // Hardware Setup
  pinMode(PIN_L_A, INPUT_PULLUP); pinMode(PIN_L_B, INPUT_PULLUP);
  pinMode(PIN_R_A, INPUT_PULLUP); pinMode(PIN_R_B, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_L_A), countLeft, RISING);
  attachInterrupt(digitalPinToInterrupt(PIN_R_A), countRight, RISING);

  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  pinMode(LIMIT_SWITCH, INPUT_PULLUP);
  
  stopMotors();

  // IMU Setup
  if (!mpu.begin()) {
    Serial.println("MPU6050 NOT FOUND!");
  } else {
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_250_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_44_HZ); 
    calibrateIMU();
  }
}

void loop() {
  // Reset Watchdog timer at the start of every successful loop
  wdt_reset(); 

  unsigned long currentMillis = millis();

  // --- 1. Serial Command Handling ---
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == 'I' || cmd == 'i') {
      movingIn = true; movingOut = false;
    } 
    else if (cmd == 'O' || cmd == 'o') {
      movingOut = true; movingIn = false;
      moveOutStartTime = currentMillis; 
    } 
    else if (cmd == 'S' || cmd == 's') {
      movingIn = false; movingOut = false;
      stopMotors();
      Serial.println("STATUS: STOPPED");
    }
  }

  // --- 2. Motor Logic ---
  if (movingIn) {
    if (digitalRead(LIMIT_SWITCH) == LOW) { 
      stopMotors();
      movingIn = false;
      Serial.println("STATUS: IN_LIMIT_HIT"); 
    } else {
      pullTrayIn();
    }
  } 
  else if (movingOut) {
    if (currentMillis - moveOutStartTime >= OUT_DURATION) {
      stopMotors();
      movingOut = false;
      Serial.println("STATUS: OUT_COMPLETE");
    } else {
      pushTrayOut();
    }
  }

  // --- 3. Telemetry (50Hz) ---
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;
    
    noInterrupts();
    long l_ticks = left_ticks;
    long r_ticks = right_ticks;
    interrupts();

    sensors_event_t a, g, temp;
    // getEvent will return false if the WireTimeout triggers
    if (mpu.getEvent(&a, &g, &temp)) {
      Serial.print("L:"); Serial.print(l_ticks);
      Serial.print(",R:"); Serial.print(r_ticks);
      Serial.print(",GX:"); Serial.print(g.gyro.x - gx_offset, 4);
      Serial.print(",GY:"); Serial.print(g.gyro.y - gy_offset, 4);
      Serial.print(",GZ:"); Serial.print(g.gyro.z - gz_offset, 4);
      Serial.print(",AX:"); Serial.print(a.acceleration.x - ax_offset, 2);
      Serial.print(",AY:"); Serial.print(a.acceleration.y - ay_offset, 2);
      Serial.print(",AZ:"); Serial.println(a.acceleration.z - az_offset, 2);
    }
  }
}

// --- Functions ---

void calibrateIMU() {
  int num_readings = 500;
  sensors_event_t a, g, temp;
  for (int i = 0; i < num_readings; i++) {
    wdt_reset(); // Don't let watchdog reset during calibration
    mpu.getEvent(&a, &g, &temp);
    gx_offset += g.gyro.x; gy_offset += g.gyro.y; gz_offset += g.gyro.z;
    ax_offset += a.acceleration.x; ay_offset += a.acceleration.y;
    az_offset += (a.acceleration.z - 9.81); 
    delay(3); 
  }
  gx_offset /= num_readings; gy_offset /= num_readings; gz_offset /= num_readings;
  ax_offset /= num_readings; ay_offset /= num_readings; az_offset /= num_readings;
}

void pullTrayIn() {
  digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
  digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
}

void pushTrayOut() {
  digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);
  digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH);
}

void stopMotors() {
  digitalWrite(IN1, LOW); digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW); digitalWrite(IN4, LOW);
}

void countLeft() {
  if (digitalRead(PIN_L_B) == LOW) left_ticks++; else left_ticks--;
}

void countRight() {
  if (digitalRead(PIN_R_B) == LOW) right_ticks--; else right_ticks++;
}