#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from lib.observer import EmbyObserverService
from lib.utils import log


if __name__ == '__main__':
    # instantiate and start the observer service
    log('Emby Media Import observer started')
    EmbyObserverService()
