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

import os
import oci
import mock
import unittest
from helpers import TestDbManager
from tortuga.resourceAdapter.oracleadapter import Oracleadapter, OciSession


class TestOracleCloudSession(unittest.TestCase):
    def setUp(self):
        self.override_config = {
            'shape': 'foo-bar'
        }
        self.session = OciSession(self.override_config)

    def tearDown(self):
        pass

    def testOverride(self):
        for key in list(self.override_config.keys()):
            self.assertEqual(
                self.override_config[key],
                self.session.config[key],
                'OciSession has not overridden settings.'
            )

    def testLaunchConfig(self):
        self.assertEqual(
            type(self.session.launch_config),
            oci.core.models.LaunchInstanceDetails,
            'Launch config not correct type.'
        )

    @mock.patch('__builtin__.open', create=True)
    def testSshRead(self, mock_open):
        home_dir = os.path.expanduser('~')
        pub_key_path = os.path.join(home_dir, '.ssh/id_rsa.pub')
        mock_contents = 'mysshkey'

        mock_open.side_effect = [
            mock.mock_open(read_data=mock_contents).return_value
        ]

        self.assertEqual(
            mock_contents,
            self.session._get_ssh_key(),
            'Method is not returning correct contents.'
        )

        mock_open.assert_called_once_with(pub_key_path)
        mock_open.reset_mock()


class TestOracleAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = self.getMockedAdapter()

    def tearDown(self):
        pass

    @mock.patch('tortuga.db.dbManager.DbManager', new_callable=TestDbManager)
    def getMockedAdapter(self, mock_db):
        return Oracleadapter()

    def testName(self):
        self.assertEqual(
            self.adapter.__adaptername__,
            'oraclecloud',
            'Adapter name is not correct'
        )

    def testGetEncodedList(self):
        items = ['foo', 'bar']
        self.assertEqual(
            self.adapter.__get_encoded_list(items),
            "['foo', 'bar']",
            'String is not being encoded correctly.'
        )

    @mock.patch('self.adapter.installer_public_ipaddress', '10.0.0.1')
    def testGetInstallerIP(self):
        ip = '10.0.0.1'

        self.assertEqual(
            self.adapter.__get_installer_ip(None),
            ip,
            'Incorrect IP being returned.'
        )

    def testGetCommonUserDataContent(self):
        settings_dict = {
            'installerHostName': 'foo',
            'installerIp': 'foo',
            'adminport': 'foo',
            'cfmuser': 'foo',
            'cfmpassword': 'foo',
            'override_dns_domain': 'foo',
            'dns_options': 'foo',
            'dns_search': 'foo',
            'dns_nameservers': 'foo'
        }

        expected = """\
installerHostName = 'foo'
installerIpAddress = foo
port = foo
cfmUser = 'foo'
cfmPassword = 'foo'

# DNS resolution settings
override_dns_domain = foo
dns_options = foo
dns_search = foo
dns_nameservers = foo
"""

        self.assertEqual(
            expected,
            self.adapter.__get_common_user_data_content(
                settings_dict
            )
        )

    @mock.patch('self.adapter.installer_public_hostname', 'foo')
    @mock.patch('self.adapter._cm.getAdminPort', 8000)
    @mock.patch('self.adapter._cm.getCfmUser', 'foo')
    @mock.patch('self.adapter._cm.getCfmPassword', 'foo')
    def testGetCommonUserDataSettings(self):
        config_dict = {
            'override_dns_domain': 'foo',
            'dns_options': 'foo',
            'dns_search': 'foo',
            'dns_nameservers': 'foo'
        }

        expected = {
            'installerHostName': 'foo',
            'installerIp': 'None',
            'adminport': 8000,
            'cfmuser': 'foo',
            'cfmpassword': 'foo',
            'override_dns_domain': 'foo',
            'dns_options': 'foo',
            'dns_search': 'foo',
            'dns_nameservers': 'foo',
        }

        self.assertEqual(
            expected,
            self.adapter.__get_common_user_data_settings(
                config_dict
            )
        )

