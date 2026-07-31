# -*- coding: utf-8 -*-
##############################################################################
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging
# Reduce werkzeug HTTP access log noise (only show warnings/errors)
#logging.getLogger('werkzeug').setLevel(logging.WARNING)

from . import models
from . import controllers
from . import wizard

from odoo import api, SUPERUSER_ID
from .hooks import post_init_hook as _init_cron_status


def post_init_hook(env):
    """
    Post-init hook called after module installation/update.
    Uses the new cr-less signature for Odoo 17+.
    """
    # Initialize CRON status records for existing accounts
    _init_cron_status(env)


def _post_init_hook(cr, registry):
    """Legacy post_init_hook for compatibility."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Initialize CRON status records for existing accounts
    _init_cron_status(env)
