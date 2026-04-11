import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/santi/mushroom_farm_ws/src/chambers/fc-core/install/fc_core'
