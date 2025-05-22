const WebSocket = require('ws');
const rclnodejs = require('rclnodejs');

// Initialize ROS
rclnodejs.init().then(() => {
    const node = new rclnodejs.Node('mission_control_bridge');
    
    // Create WebSocket server
    const wss = new WebSocket.Server({ port: 8081 });
    
    // Store connected clients
    const clients = new Set();
    
    // Subscribe to ROS topics
    const tempSub = node.createSubscription(
        'sensor_msgs/msg/Temperature',
        'fc/temperature',
        (msg) => {
            // Broadcast to all connected clients
            const data = {
                temperature: msg.temperature,
                timestamp: Date.now()
            };
            broadcast(data);
        }
    );
    
    const humiditySub = node.createSubscription(
        'sensor_msgs/msg/RelativeHumidity',
        'fc/humidity',
        (msg) => {
            // Broadcast to all connected clients
            const data = {
                humidity: msg.relative_humidity * 100, // Convert to percentage
                timestamp: Date.now()
            };
            broadcast(data);
        }
    );
    
    // Handle WebSocket connections
    wss.on('connection', (ws) => {
        console.log('New client connected');
        clients.add(ws);
        
        ws.on('close', () => {
            console.log('Client disconnected');
            clients.delete(ws);
        });
    });
    
    // Broadcast data to all connected clients
    function broadcast(data) {
        clients.forEach(client => {
            if (client.readyState === WebSocket.OPEN) {
                client.send(JSON.stringify(data));
            }
        });
    }
    
    // Start ROS node
    node.spin();
    
    console.log('Bridge service started on port 8081');
}).catch((err) => {
    console.error('Failed to initialize ROS:', err);
    process.exit(1);
}); 