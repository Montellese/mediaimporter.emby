#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

class Plugin:
    class Serialization:
        PROPERTY_ID = 'Id'
        PROPERTY_NAME = 'Name'
        PROPERTY_DESCRIPTION = 'Description'
        PROPERTY_VERSION = 'Version'
        PROPERTY_IMAGE_TAG = 'ImageTag'

    def __init__(self, identifier, name, description=None, version=None, imageTag=None):
        self.id = identifier
        self.name = name
        self.description = description
        self.version = version
        self.imageTag = imageTag

    @staticmethod
    def GetPlugins(embyServer):
        if not embyServer:
            raise ValueError('invalid embyServer')

        pluginsUrl = embyServer.BuildPluginUrl()
        pluginsObj = embyServer.ApiGet(pluginsUrl)
        if not pluginsObj:
            return []

        plugins = []
        for pluginObj in pluginsObj:
            if not Plugin.Serialization.PROPERTY_ID in pluginObj or \
                not Plugin.Serialization.PROPERTY_NAME in pluginObj:
                continue
            
            identifier = pluginObj[Plugin.Serialization.PROPERTY_ID]
            name = pluginObj[Plugin.Serialization.PROPERTY_NAME]
            description = None
            if Plugin.Serialization.PROPERTY_DESCRIPTION in pluginObj:
                description = pluginObj[Plugin.Serialization.PROPERTY_DESCRIPTION]
            version = None
            if Plugin.Serialization.PROPERTY_VERSION in pluginObj:
                version = pluginObj[Plugin.Serialization.PROPERTY_VERSION]
            imageTag = None
            if Plugin.Serialization.PROPERTY_IMAGE_TAG in pluginObj:
                imageTag = pluginObj[Plugin.Serialization.PROPERTY_IMAGE_TAG]

            plugins.append(Plugin(identifier, name, description=description, version=version, imageTag=imageTag))

        return plugins
