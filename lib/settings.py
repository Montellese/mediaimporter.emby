#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from emby.constants import \
    SETTING_IMPORT_VIEWS, \
    SETTING_IMPORT_VIEWS_OPTION_SPECIFIC, \
    SETTING_IMPORT_VIEWS_SPECIFIC

class ImportSettings:
    @staticmethod
    def GetLibraryViews(importSettings):
        if not importSettings:
            raise ValueError('invalid importSettings')

        if not importSettings.getString(SETTING_IMPORT_VIEWS) == SETTING_IMPORT_VIEWS_OPTION_SPECIFIC:
            return []

        return importSettings.getStringList(SETTING_IMPORT_VIEWS_SPECIFIC)
