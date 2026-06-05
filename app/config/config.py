from datetime import timedelta
from random import choice
from string import ascii_letters, digits, punctuation

from pygal import Config
from pygal.style import Style

from app.config.menu import menu_tree

# Deployment configuration is stored in this file.
# #############################################################################################

# Flask debug. Turning it to True leads to unexpected behaviour: internal threads will be started twice.
DEBUG = True

# Flask secret key. Set this key to a fixed value to keep user sessions valid even if your server is restarted.
SECRET_KEY = ''.join([choice(ascii_letters + digits + punctuation) for n in range(32)])

# [REQUIRED]
# On production set host to 0.0.0.0, choose port and proper server_name (must include port, mycompany.com:8181).
# It is possible to use default local settings, but note that Chrome may not send a cookie to localhost.
# See the official Flask docs to learn more about these params.
HOST = '127.0.0.1'  # [REQUIRED]
PORT = 5000
SERVER_NAME = None
CUSTOM_SERVER_NAME = None

# How much time client browser should keep our cookies.
PERMANENT_USER_SESSION = True
PERMANENT_SESSION_LIFETIME = timedelta(days=7)

# Limit parallel queries count for each user
MAX_DB_SESSIONS_PER_USER = 20

# How many rows can be fetched
ORA_NUM_ROWS = 100_000

# Limit parallel session count for each target
ORA_MAX_POOL_SIZE = 40

# Datetime display format
DATETIME_FORMAT = '%d.%m.%Y %H:%M:%S'

# The main menu structure. Can be imported from other source.
MENU_TREE = menu_tree

# Logger params
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 3
ERROR_LOG_NAME = 'error.log'
ACCESS_LOG_NAME = 'access.log'
ENABLE_ACCESS_LOG = False

# Pygal charts configuration. See the official Pygal docs.
CHART_CONFIG = {'style': Style(font_family='Arial'
                               , guide_stroke_dasharray='1,1'
                               , major_guide_stroke_dasharray='1,1'
                               , label_font_size=12
                               , major_label_font_size=12
                               , value_font_size=12
                               , value_label_font_size=12
                               , legend_font_size=12
                               , background='#FFFFFF'
                               , plot_background='#FFFFFF'
                               , title_font_family='Arial'
                               , title_font_size=12)
                , 'explicit_size': True
                , 'height': 400
                , 'width': 1000
                , 'margin': 4
                , 'show_x_guides': True
                , 'tooltip_border_radius': 2
                , 'dots_size': 2
                , 'stroke_style': {'width': 1}}


# Database targets are now managed via the web UI and stored in a persistent
# SQLite store. Keep an empty mapping here so templates and code referencing
# `config['TARGETS']` continue to work.
TARGETS = {}

# [REQUIRED]
# Add users to the system.
# key = login (str), must be in a lowercase.
# value[0] = password (str).
# value[1] = list of targets (str) allowed to user.
# Users are now managed via the web UI and stored in a persistent SQLite store.
# Keep an empty mapping for compatibility.
USERS = {}

# [REQUIRED]
# List of users, which allowed to:
# - shutdown the app server;
ADMIN_GROUP = []
ADMIN_ONLY_VIEWS = ['get_access_log', 'get_error_log', 'stop_server']

# If your custom view is specific for some target it will not be shown for other targets.
# {view_name: [target_name1, target_name2, ...], ...}
TARGET_SPECIFIC_VIEWS = {}

# Configuration is fully defined in this file.
# Finishing touch
CHART_CONFIG['config'] = Config(js=[f'http://{SERVER_NAME or CUSTOM_SERVER_NAME or (HOST + ":" + str(PORT))}'
                                    f'/static/pygal-tooltips.min.js'])

# That's all. Now try to start the app. Good luck!
