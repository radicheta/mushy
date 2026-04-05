#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Temperature, RelativeHumidity
import websockets
import asyncio
import json
import threading
from datetime import datetime

class FruitingChamberTelemetry(Node):
    def __init__(self):
        super().__init__('fc_telemetry')
        
        # ROS2 subscribers
        self.temp_sub = self.create_subscription(
            Temperature,
            'fc1/temperature',
            self.temp_callback,
            10)
            
        self.humidity_sub = self.create_subscription(
            RelativeHumidity,
            'fc1/humidity',
            self.humidity_callback,
            10)
            
        # Latest values
        self.temperature = 0.0
        self.humidity = 0.0
        
        # Start WebSocket server in a separate thread
        self.ws_thread = threading.Thread(target=self.run_websocket_server)
        self.ws_thread.daemon = True
        self.ws_thread.start()
        
        self.get_logger().info('Fruiting Chamber Telemetry Node Started')
        
    def temp_callback(self, msg):
        self.temperature = msg.temperature
        self.get_logger().debug(f'Received temperature: {self.temperature}°C')
        
    def humidity_callback(self, msg):
        self.humidity = msg.relative_humidity * 100.0  # Convert to percentage
        self.get_logger().debug(f'Received humidity: {self.humidity}%')
        
    async def handle_websocket(self, websocket):
        while True:
            # Create telemetry packet
            telemetry = {
                'timestamp': datetime.utcnow().isoformat(),
                'temperature': self.temperature,
                'humidity': self.humidity
            }
            
            # Send to OpenMCT
            await websocket.send(json.dumps(telemetry))
            await asyncio.sleep(1.0)  # Update every second
            
    async def websocket_server(self):
        async with websockets.serve(self.handle_websocket, "localhost", 8081):
            await asyncio.Future()  # run forever
            
    def run_websocket_server(self):
        asyncio.run(self.websocket_server())

def main(args=None):
    rclpy.init(args=args)
    node = FruitingChamberTelemetry()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main() 