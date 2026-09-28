std_msgs/Header header

# Actual physical state from encoder feedback (NaN if encoder absent/stale)
float64 position_deg
float64 velocity_deg_s

# Commanded target state
float64 target_position_deg

# Motion and settling indicators
bool moving
bool at_target

# Hardware & safety status
bool enabled
bool watchdog_healthy
bool encoder_valid
uint8 fault_code

# Position authority & fallback abstraction
string position_source
bool encoder_available
bool encoder_stale
float64 actual_yaw_deg
float64 estimated_yaw_deg
