from __future__ import annotations

import logging
import os.path

from flask import Flask
from flask_babelhg import get_locale
from flask_executor import Executor
from flask_flatpages import FlatPages
from flask_mailman import Mail
from flask_migrate import Migrate
from flask_redis import FlaskRedis
from flask_rq2 import RQ

import geoip2.database

from baseframe import Bundle, Version, assets, baseframe
import coaster.app

from ._version import __version__

#: Main app for hasgeek.com
app = Flask(__name__, instance_relative_config=True)
#: Shortlink app at has.gy
shortlinkapp = Flask(__name__, static_folder=None, instance_relative_config=True)

mail = Mail()
pages = FlatPages()
redis_store = FlaskRedis(decode_responses=True)
rq = RQ()
executor = Executor()

# --- Assets ------------------------------------------------------------------

version = Version(__version__)
assets['funnel.css'][version] = 'css/app.css'
assets['funnel.js'][version] = 'js/scripts.js'
assets['spectrum.js'][version] = 'js/libs/spectrum.js'
assets['spectrum.css'][version] = 'css/spectrum.css'
assets['screens.css'][version] = 'css/screens.css'
assets['schedules.js'][version] = 'js/schedules.js'
assets['schedule-print.css'][version] = 'css/schedule-print.css'


# --- Import rest of the app --------------------------------------------------

from . import (  # isort:skip  # noqa: F401
    models,
    signals,
    forms,
    loginproviders,
    transports,
    views,
    cli,
)
from .models import db  # isort:skip

# --- Configuration------------------------------------------------------------
coaster.app.init_app(app)
coaster.app.init_app(shortlinkapp, init_logging=False)

# These are app specific confguration files that must exist
# inside the `instance/` directory. Sample config files are
# provided as example.
coaster.app.load_config_from_file(app, 'hasgeekapp.py')
shortlinkapp.config['SERVER_NAME'] = app.config['SHORTLINK_DOMAIN']

# Downgrade logging from default WARNING level to INFO
for _logging_app in (app, shortlinkapp):
    if not _logging_app.debug:
        _logging_app.logger.setLevel(logging.INFO)

# TODO: Move this into Baseframe
app.jinja_env.globals['get_locale'] = get_locale

# TODO: Replace this with something cleaner. The `login_manager` attr expectation is
# from coaster.auth. It attempts to call `current_app.login_manager._load_user`, an
# API it borrows from the Flask-Login extension
app.login_manager = views.login_session.LoginManager()

db.init_app(app)
db.init_app(shortlinkapp)
db.app = app

migrate = Migrate(app, db)

mail.init_app(app)
mail.init_app(shortlinkapp)  # Required for email error reports

app.config['FLATPAGES_MARKDOWN_EXTENSIONS'] = ['markdown.extensions.nl2br']
pages.init_app(app)

redis_store.init_app(app)

rq.init_app(app)

executor.init_app(app)

baseframe.init_app(
    app,
    requires=['funnel'],
    ext_requires=[
        'pygments',
        'toastr',
        'baseframe-mui',
        'jquery.cookie',
        'timezone',
        'pace',
    ],
    theme='mui',
    asset_modules=('baseframe_private_assets',),
)

loginproviders.init_app(app)

# Load GeoIP2 databases
app.geoip_city = None
app.geoip_asn = None
if 'GEOIP_DB_CITY' in app.config:
    if not os.path.exists(app.config['GEOIP_DB_CITY']):
        app.logger.warning(
            "GeoIP city database missing at %s", app.config['GEOIP_DB_CITY']
        )
    else:
        app.geoip_city = geoip2.database.Reader(app.config['GEOIP_DB_CITY'])

if 'GEOIP_DB_ASN' in app.config:
    if not os.path.exists(app.config['GEOIP_DB_ASN']):
        app.logger.warning(
            "GeoIP ASN database missing at %s", app.config['GEOIP_DB_ASN']
        )
    else:
        app.geoip_asn = geoip2.database.Reader(app.config['GEOIP_DB_ASN'])

# Turn on supported notification transports
transports.init()

# Register JS and CSS assets on both apps
app.assets.register(
    'js_fullcalendar',
    Bundle(
        assets.require(
            '!jquery.js',
            'jquery.fullcalendar.js',
            'moment.js',
            'moment-timezone-data.js',
            'spectrum.js',
            'jquery.ui.sortable.touch.js',
        ),
        output='js/fullcalendar.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'css_fullcalendar',
    Bundle(
        assets.require('jquery.fullcalendar.css', 'spectrum.css'),
        output='css/fullcalendar.packed.css',
        filters='cssmin',
    ),
)
app.assets.register(
    'js_schedules',
    Bundle(
        assets.require('schedules.js'),
        output='js/schedules.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'js_codemirrormarkdown',
    Bundle(
        assets.require('codemirror-markdown.js'),
        output='js/codemirror-markdown.packed.js',
    ),
)
app.assets.register(
    'css_codemirrormarkdown',
    Bundle(
        assets.require('codemirror-markdown-material.css'),
        output='css/codemirror-markdown.packed.css',
        filters='cssmin',
    ),
)
app.assets.register(
    'css_screens',
    Bundle(
        assets.require('screens.css'), output='css/screens.packed.css', filters='cssmin'
    ),
)
app.assets.register(
    'js_jquerytruncate',
    Bundle(
        assets.require('!jquery.js', 'jquery.truncate8.js'),
        output='js/jquerytruncate.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'js_jqueryeasytabs',
    Bundle(
        assets.require('!jquery.js', 'jquery-easytabs.js'),
        output='js/jqueryeasytabs.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'js_leaflet',
    Bundle(
        assets.require('leaflet.js', 'leaflet-search.js'),
        output='js/leaflet.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'css_leaflet',
    Bundle(
        assets.require('leaflet.css', 'leaflet-search.css'),
        output='css/leaflet.packed.css',
        filters='cssmin',
    ),
)
app.assets.register(
    'js_emojionearea',
    Bundle(
        assets.require('!jquery.js', 'emojionearea-material.js'),
        output='js/emojionearea.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'css_emojionearea',
    Bundle(
        assets.require('emojionearea-material.css'),
        output='css/emojionearea.packed.css',
        filters='cssmin',
    ),
)
app.assets.register(
    'js_sortable',
    Bundle(
        assets.require('!jquery.js', 'jquery.ui.js', 'jquery.ui.sortable.touch.js'),
        output='js/sortable.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'css_schedule_print',
    Bundle(
        assets.require('schedule-print.css'),
        output='css/schedule-print.packed.css',
        filters='cssmin',
    ),
)
app.assets.register(
    'js_footable',
    Bundle(
        assets.require('!jquery.js', 'baseframe-footable.js'),
        output='js/footable.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'js_footable_paginate',
    Bundle(
        assets.require('!jquery.js', 'footable-paginate.js'),
        output='js/footable_paginate.packed.js',
        filters='uglipyjs',
    ),
)
app.assets.register(
    'css_footable',
    Bundle(
        assets.require('baseframe-footable-mui.css'),
        output='css/footable.packed.css',
        filters='cssmin',
    ),
)

# Database model loading (from Funnel or extensions) is complete.
# Configure database mappers now, before the process is forked for workers.
db.configure_mappers()
