#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import sys

from six.moves.urllib.parse import parse_qs

from lib import context
from lib.utils import log

OPTION_ACTION = 'action'

if __name__ == '__main__':
    if len(sys.argv) < 2:
        log('Emby Media Import Context called with too few arguments')
        sys.exit(1)

    # get the options but remove the leading ?
    args = sys.argv[1][1:]
    if not args:
        log('Emby Media Import Context called with invalid arguments')
        sys.exit(1)

    options = parse_qs(args)
    if OPTION_ACTION not in options:
        log('Emby Media Import Context called with missing "action" argument')
        sys.exit(1)

    action = None
    action_option = options[OPTION_ACTION][0]
    if action_option == 'play':
        action = context.ContextAction.Play
    elif action_option == 'sync':
        action = context.ContextAction.Synchronize
    elif action_option == 'refresh':
        action = context.ContextAction.RefreshMetadata
    else:
        log('Emby Media Import Context called with unknown "{}" argument: {}'.format(OPTION_ACTION, action_option))
        sys.exit(1)

    log('Emby Media Import {} context menu item started'.format(action_option))
    context.run(action)
