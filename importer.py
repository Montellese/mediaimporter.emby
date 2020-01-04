#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import sys

from lib import importer
from lib.utils import log


if __name__ == '__main__':
    log('Emby Media Import importer started')
    importer.run(sys.argv)
