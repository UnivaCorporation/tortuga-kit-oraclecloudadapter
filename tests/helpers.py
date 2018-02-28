# Copyright 2008-2018 Univa Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sqlalchemy
from tortuga.db.dbManager import DbManagerBase
from tortuga.config.configManager import ConfigManager


class TestDbManager(DbManagerBase):
    def __init__(self):
        self._cm = ConfigManager()
        self._engine = sqlalchemy.create_engine('sqlite://')
        self._metadata = sqlalchemy.MetaData(self._engine)
        self.__mapDbTables()
        self.Session = None
        self.init_database()

    def init_database(self):
        self._metadata.create_all(self._engine)

    def __mapDbTables(self):
        from tortuga.db import networks
        networks.mapTable(self)

        from tortuga.db import kitSources
        kitSources.mapTable(self)

        from tortuga.db import softwareProfileKitSources
        softwareProfileKitSources.mapTable(self)

        from tortuga.db import admins
        admins.mapTable(self)

        from tortuga.db import networkDevices
        networkDevices.mapTable(self)

        from tortuga.db import tags
        tags.mapTable(self)

        from tortuga.db import nodeTags
        nodeTags.mapTable(self)

        from tortuga.db import softwareProfileTags
        softwareProfileTags.mapTable(self)

        from tortuga.db import hardwareProfileTags
        hardwareProfileTags.mapTable(self)

        from tortuga.db import hardwareProfileNetworks
        hardwareProfileNetworks.mapTable(self)

        from tortuga.db import hardwareProfiles
        hardwareProfiles.mapTable(self)

        from tortuga.db import softwareProfileComponents
        softwareProfileComponents.mapTable(self)

        from tortuga.db import softwareUsesHardware
        softwareUsesHardware.mapTable(self)

        from tortuga.db import softwareProfiles
        softwareProfiles.mapTable(self)

        from tortuga.db import globalParameters
        globalParameters.mapTable(self)

        from tortuga.db import nics
        nics.mapTable(self)

        from tortuga.db import nodes
        nodes.mapTable(self)

        from tortuga.db import operatingSystemsFamilies
        operatingSystemsFamilies.mapTable(self)

        from tortuga.db import operatingSystems
        operatingSystems.mapTable(self)

        from tortuga.db import osComponents
        osComponents.mapTable(self)

        from tortuga.db import osFamilyComponents
        osFamilyComponents.mapTable(self)

        from tortuga.db import components
        components.mapTable(self)

        from tortuga.db import packages
        packages.mapTable(self)

        from tortuga.db import partitions
        partitions.mapTable(self)

        from tortuga.db import resourceAdapters
        resourceAdapters.mapTable(self)

        from tortuga.db import nodeRequests
        nodeRequests.mapTable(self)

        from tortuga.db import uge_clusters, uge_clusters_kv, \
            uge_clusters_swprofiles
        uge_clusters_swprofiles.mapTable(self)
        uge_clusters.mapTable(self)
        uge_clusters_kv.mapTable(self)

        from tortuga.db import resourceAdapterCredentials
        resourceAdapterCredentials.mapTable(self)
