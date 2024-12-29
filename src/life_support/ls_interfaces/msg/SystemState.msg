std_msgs/Header header

string system_id      # Identifier for specific chamber/incubator
string mode          # Current operation mode (e.g., "NORMAL", "MAINTENANCE", "ERROR")
bool online          # System online status
string[] active_warnings  # List of any current warnings
string[] active_errors    # List of any current errors
