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

import itertools
import json
import logging
import os
import sys
from base64 import b64encode
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.request import urlopen

import gevent

import oci
from tortuga.config.configManager import ConfigManager
from tortuga.db.models.nic import Nic
from tortuga.db.models.node import Node
from tortuga.exceptions.configurationError import ConfigurationError
from tortuga.exceptions.resourceNotFound import ResourceNotFound
from tortuga.os_utility import osUtility
from tortuga.resourceAdapter.resourceAdapter import ResourceAdapter
from tortuga.resourceAdapter.utility import StopWatch, get_random_sleep_time


class OciSession(object):
    """
    Stores configuration for a session
    with OCI.
    """
    def __init__(self, override_config=None):
        """
        Set defaults, unless overridden.  Then
        set class attributes.

        :availability_domain: String id
        :compartment_id: String id
        :shape: String node type
        :subnet_id: String id
        :image_id: String id
        :ssh_authorized_keys: List Strings ssh public keys

        :param override_config: Dictionary to merge with defaults
        :return: OciSession instance
        """
        self.config = {
            'availability_domain': None,
            'compartment_id': None,
            'shape': 'VM.Standard1.1',
            'vcpus': None,
            'subnet_id': None,
            'image_id': None,
            'user_data_script_template': os.path.join(
                ConfigManager().getKitConfigBase(),
                'oci_bootstrap.tmpl'),
            'override_dns_domain': False,
            'dns_options': None,
            'dns_search': None,
            'dns_nameservers': None,
            'metadata': {
                'ssh_authorized_keys': self._get_ssh_key()
            }
        }

        if override_config and isinstance(override_config, dict):
            self.config.update(override_config)

        if not self.config['vcpus']:
            self.config['vcpus'] = self.cores_from_shape

    def _validate_config(self):
        """
        Make sure all the needed keys are defined.
        :return: None
        """
        required = [
            'availability_domain',
            'compartment_id',
            'subnet_id',
            'image_id'
        ]

        for key in required:
            if not self.config[key]:
                raise RuntimeError('%s is missing from config' % key)

    @property
    def launch_config(self):
        """
        Build launch dictionary for OCI.

        :return: Dictionary config
        """
        launch_dict = oci.core.models.LaunchInstanceDetails()
        launch_keys = [
            'availability_domain',
            'compartment_id',
            'shape',
            'subnet_id',
            'image_id',
            'metadata'
        ]

        for key, value in list(self.config.items()):
            if key in launch_keys:
                setattr(launch_dict, key, value)

        return launch_dict

    @property
    def cores_from_shape(self):
        """
        Cores of shape for UGE slots.

        :return: Integer cores
        """
        return int(self.config['shape'].split('.')[-1])

    @staticmethod
    def _get_ssh_key():
        """
        Find ssh public key, open it
        and return contents as a string.

        :return: String ssh public key
        """
        home_dir = os.path.expanduser('~')
        pub_key_path = os.path.join(home_dir, '.ssh/id_rsa.pub')
        if os.path.isfile(pub_key_path):
            with open(pub_key_path) as f:
                return f.read().strip()


class Oracleadapter(ResourceAdapter):
    """
    Drive Oracle Cloud Infrastructure.
    """
    __adaptername__ = 'oraclecloud'

    def __init__(self, addHostSession=None):
        """
        Upon instantiation, read and validate config file.

        :return: Oci instance
        """
        super(Oracleadapter, self).__init__(addHostSession=addHostSession)

        config = {
            'region': None,
            'log_requests': False,
            'tenancy': None,
            'user': None,
            'pass_phrase': None,
            'fingerprint': None,
            'additional_user_agent': '',
            'key_file': os.path.join(os.path.expanduser('~'), '.ssh/id_rsa')
        }

        override_config = self.getResourceAdapterConfig()
        if override_config and isinstance(override_config, dict):
            config.update(override_config)

        oci.config.validate_config(config)
        self.__vcpus = None
        self.__installer_ip = None
        self.__client = oci.core.compute_client.ComputeClient(config)
        self.__net_client = \
            oci.core.virtual_network_client.VirtualNetworkClient(config)
        self.__identity_client = \
            oci.identity.identity_client.IdentityClient(config)

    def __validate_keys(self, config):
        """
        Check all the required keys exist.

        :param config: Dictionary
        :return: None
        """
        provided_keys = set(config.keys())
        required_keys = {
            'availability_domain',
            'compartment_id',
            'shape',
            'subnet_id',
            'image_id'
        }

        missing_keys = required_keys.difference(provided_keys)

        if missing_keys:
            error_message = \
                'Required configuration setting(s) [%s] are missing' % (
                    ' '.join(missing_keys)
                )

            self.getLogger().error(error_message)

    def getResourceAdapterConfig(self, sectionName=None):
        """
        Get resource adapter configuration dict

        Raises:
            ConfigurationError

        :arg sectionName: resource adapter configuration profile name
        :return: dict containing resource adapter configuration
        :rtype: dict
        """
        configDict = super(Oracleadapter, self).getResourceAdapterConfig(
            sectionName=sectionName)

        if 'user_data_script_template' in configDict:
            if not configDict['user_data_script_template'].startswith('/'):
                fn = os.path.join(
                    self._cm.getKitConfigBase(),
                    configDict['user_data_script_template'])
            else:
                fn = configDict['user_data_script_template']

            if not os.path.exists(fn):
                raise ConfigurationError(
                    'User data script template [%s] does not exist' % fn
                )

            configDict['user_data_script_template'] = fn

        return configDict

    @staticmethod
    def __cloud_instance_metadata():
        """
        Get the cloud metadata.

        :returns: Dictionary metadata
        """
        response = urlopen('http://169.254.169.254/opc/v1/instance/')
        return json.load(response)

    @staticmethod
    def __cloud_vnic_metadata():
        """
        Get the VNIC cloud metadata.

        :returns: Dictionary metadata
        """
        response = urlopen('http://169.254.169.254/opc/v1/vnics/')
        return json.load(response)

    @property
    def __cloud_launch_metadata(self):
        """
        Get metadata needed to create metadata.

        :returns: Dictionary metadata
        """
        compute = self.__cloud_instance_metadata()
        vnic = self.__cloud_vnic_metadata()

        full_vnic = self.__net_client.get_vnic(
            vnic['vnicId']
        ).data

        return {
            'availability_domain': compute['availabilityDomain'],
            'compartment_id': compute['compartmentId'],
            'subnet_id': full_vnic.subnet_id,
            'image_id': compute['image'],
            'region': compute['region'],
            'tenancy_id': '',
            'user_id': '',
            'shape': compute['shape']
        }

    def start(self, addNodesRequest, dbSession, dbHardwareProfile,
              dbSoftwareProfile=None):
        """
        Create a cloud and bind with Tortuga.

        :return: List Instance objects
        """
        self.getLogger().debug(
            'start(): addNodesRequest=[%s], dbSession=[%s],'
            ' dbHardwareProfile=[%s], dbSoftwareProfile=[%s]' % (
                addNodesRequest,
                dbSession,
                dbHardwareProfile,
                dbSoftwareProfile
            )
        )

        with StopWatch() as stop_watch:
            nodes = self.__add_nodes(
                addNodesRequest,
                dbSession,
                dbHardwareProfile,
                dbSoftwareProfile
            )

        if len(nodes) < addNodesRequest['count']:
            self.getLogger().warning(
                '%s node(s) requested, only %s launched'
                ' successfully' % (
                    addNodesRequest['count'],
                    len(nodes)
                )
            )

        self.getLogger().debug(
            'start() session [%s] completed in'
            ' %0.2f seconds' % (
                self.addHostSession,
                stop_watch.result.seconds +
                stop_watch.result.microseconds / 1000000.0
            )
        )

        self.addHostApi.clear_session_nodes(nodes)

        return nodes

    def __add_nodes(self, add_nodes_request, db_session, db_hardware_profile,
                    db_software_profile):
        """
        Add nodes to the infrastructure.

        :return: List Nodes objects
        """

        # TODO: this validation needs to be moved
        # self.__validate_keys(session.config)

        node_spec = {
            'db_hardware_profile': db_hardware_profile,
            'db_software_profile': db_software_profile,
            'db_session': db_session,
            'configDict': self.getResourceAdapterConfig(),
        }

        return self.__oci_add_nodes(
            count=int(add_nodes_request['count']),
            node_spec=node_spec)

    def __oci_add_nodes(self, count=1, node_spec=None):
        """
        Wrapper around __oci_add_node() method. Launches Greenlets to
        perform add nodes operation in parallel using gevent.

        :param count: number of nodes to add
        :param node_spec: dict containing instance launch specification
        :return: list of Nodes
        """
        greenlets = []
        for _ in range(count):
            greenlets.append(gevent.spawn(self.__oci_add_node, node_spec))

        return [result.value
                for result in gevent.iwait(greenlets) if result.value]

    def __oci_add_node(self, node_spec):
        """
        Add one node and backing instance to Tortuga.

        :param node_spec: instance launch specification
        :return: Nodes object (or None, on failure)
        """
        node_dict = self.__oci_pre_launch_instance(node_spec=node_spec)

        try:
            instance = self._launch_instance(node_dict=node_dict,
                                             node_spec=node_spec)
        except Exception as exc:
            if 'node' in node_dict:
                node_spec['db_session'].delete(node_dict['node'])
                node_spec['db_session'].commit()

            self.getLogger().error(
                'Error launching instance: [%s]' % (
                    exc)
            )

            return

        return self._instance_post_launch(
            instance, node_dict=node_dict, node_spec=node_spec)

    def __oci_pre_launch_instance(self, node_spec=None):
        """
        Creates Nodes object if Tortuga-generated host names are enabled,
        otherwise returns empty node dict.

        :param node_spec: dict containing instance launch specification
        :return: node dict
        """
        if node_spec['db_hardware_profile'].nameFormat == '*':
            return {}

        result = {}

        # Generate node name
        hostname, _ = self.addHostApi.generate_node_name(
            node_spec['db_session'],
            node_spec['db_hardware_profile'].nameFormat,
            dns_zone=self.private_dns_zone).split('.', 1)

        _, domain = self.installer_public_hostname.split('.', 1)

        name = '%s.%s' % (hostname, domain)

        # Create Nodes object
        node = self.__initialize_node(
            name,
            node_spec['db_hardware_profile'],
            node_spec['db_software_profile']
        )

        node.state = 'Launching'

        result['node'] = node

        # Add to database and commit database session
        node_spec['db_session'].add(node)
        node_spec['db_session'].commit()

        return result

    def __initialize_node(self, name, db_hardware_profile,
                          db_software_profile):
        node = Node(name=name)
        node.softwareprofile = db_software_profile
        node.hardwareprofile = db_hardware_profile
        node.isIdle = False
        node.addHostSession = self.addHostSession

        return node

    def _launch_instance(self, node_dict=None, node_spec=None):
        """
        Launch instance and wait for it to reach RUNNING state.

        :param node_dict: Dictionary
        :param node_spec: Object
        :return: Instance object
        """

        session = OciSession(node_spec['configDict'])
        session.config['metadata']['user_data'] = \
            self.__get_user_data(session.config)

        # TODO: this is a temporary workaround until the OciSession
        # functionality is validated for this workflow
        launch_config = session.launch_config

        # TODO: make this work better.  Need to
        # find a way of injecting this into the
        # `get_node_vcpus` method.
        self.__vcpus = session.config['vcpus'] if \
            session.config['vcpus'] else \
            session.cores_from_shape
        self.getLogger().debug(
            'setting vcpus to %d' % (
                self.__vcpus
            )
        )

        if 'node' in node_dict:
            node = node_dict['node']

            self.getLogger().debug(
                'overriding instance name [%s]' % (
                    node.name)
            )

            launch_config.display_name = node.name
            launch_config.hostname_label = node.name.split('.', 1)[0]

        launch_instance = self.__client.launch_instance(launch_config)

        instance_ocid = launch_instance.data.id

        node_dict['instance_ocid'] = instance_ocid

        log_adapter = CustomAdapter(
            self.getLogger(), {'instance_ocid': instance_ocid})

        log_adapter.debug('launched')

        # TODO: implement a timeout waiting for an instance to start; this
        # will currently wait forever
        # TODO: check for launch error
        def logging_callback(instance, state):
            log_adapter.debug('state: %s; waiting...' % state)

        self._wait_for_instance_state(
            instance_ocid, 'RUNNING', callback=logging_callback)

        log_adapter.debug('state: RUNNING')

        return self.__client.get_instance(instance_ocid).data

    def get_node_vcpus(self, name):
        """
        Return resolved number of VCPUs.

        :param name: String node hostname
        :return: Integer vcpus
        """
        instance_cache = self.instanceCacheGet(name)
        if 'vcpus' in list(instance_cache.keys()):
            return int(instance_cache['vcpus'])
        return self.__vcpus

    def _instance_post_launch(self, instance, node_dict=None, node_spec=None):
        """
        Called after instance has launched successfully.

        :param instance: Oracle instance
        :param node_dict: instance/node mapping dict
        :param node_spec: instance launch specification
        :return: Nodes object
        """
        self.getLogger().debug(
            'Instance post-launch action for instance [%s]' % (
                instance.id)
        )

        if 'node' not in node_dict:
            domain = self.installer_public_hostname.split('.')[1:]
            fqdn = '.'.join([instance.display_name] + domain)

            node = self.__initialize_node(
                fqdn,
                node_spec['db_hardware_profile'],
                node_spec['db_software_profile']
            )

            node_spec['db_session'].add(node)

            node_dict['node'] = node
        else:
            node = node_dict['node']

        node.state = 'Provisioned'

        # Get ip address from instance
        nics = []
        for ip in self.__get_instance_private_ips(
                instance.id, instance.compartment_id):
            nics.append(
                Nic(ip=ip, boot=True)
            )
        node.nics = nics

        node_spec['db_session'].commit()

        self.instanceCacheSet(
            node.name,
            {
                'id': instance.id,
                'compartment_id': instance.id,
                'shape': node_spec['configDict']['shape'],
                'vcpus': str(node_spec['configDict']['shape'].split('.')[-1])
            }
        )

        ip = [nic for nic in node.nics if nic.boot][0].ip

        self._pre_add_host(
            node.name,
            node.hardwareprofile.name,
            node.softwareprofile.name,
            ip)

        self.getLogger().debug(
            '_instance_post_launch(): node=[%s]' % (
                node)
        )

        return node

    def __get_instance_public_ips(self, instance_id, compartment_id):
        """
        Get public IP from the attached VNICs.

        :param instance_id: String instance id
        :param compartment_id: String compartment id
        :return: Generator String IPs
        """
        for vnic in self.__get_vnics_for_instance(instance_id, compartment_id):
            attached_vnic = self.__net_client.get_vnic(vnic.vnic_id)
            if attached_vnic:
                yield attached_vnic.data.public_ip

    def __get_instance_private_ips(self, instance_id, compartment_id):
        """
        Get private IP from the attached VNICs.

        :param instance_id: String instance id
        :param compartment_id: String compartment id
        :return: Generator String IPs
        """
        for vnic in self.__get_vnics_for_instance(instance_id, compartment_id):
            attached_vnic = self.__net_client.get_vnic(vnic.vnic_id)
            if attached_vnic:
                yield attached_vnic.data.private_ip

    def __get_vnics_for_instance(self, instance_id, compartment_id):
        """
        Get all VNICs attached to instance.

        :param instance_id: String instance id
        :param compartment_id: String compartment id
        :return: Generator VNIC objects
        """
        for vnic in self.__get_vnics(compartment_id):
            if vnic.instance_id == instance_id \
                    and vnic.lifecycle_state == 'ATTACHED':
                yield vnic

    def __get_vnics(self, compartment_id):
        """
        Get VNICs in compartment.

        :param compartment_id: String id
        :return: List VNIC objects
        """
        vnics = self.__client.list_vnic_attachments(compartment_id)

        return vnics.data

    def __get_common_user_data_settings(self, config, node=None):
        """
        Format resource adapters for the bootstrap
        template.

        :param config: Dictionary
        :param node: Node instance
        :return: Dictionary
        """
        installer_ip = self.__get_installer_ip(
            hardwareprofile=node.hardwareprofile if node else None)

        settings_dict = {
            'installerHostName': self.installer_public_hostname,
            'installerIp': '\'{0}\''.format(installer_ip)
                           if installer_ip else 'None',
            'adminport': self._cm.getAdminPort(),
            'cfmuser': self._cm.getCfmUser(),
            'cfmpassword': self._cm.getCfmPassword(),
            'override_dns_domain': str(config['override_dns_domain']),
            'dns_options': '\'{0}\''.format(config['dns_options'])
                           if config['dns_options'] else None,
            'dns_search': '\'{0}\''.format(config['dns_search'])
                          if config['dns_search'] else None,
            'dns_nameservers': self.__get_encoded_list(
                config['dns_nameservers']),
        }

        return settings_dict

    def __get_common_user_data_content(self, settings_dict):
        """
        Create header for bootstrap file.

        :param settings_dict: Dictionary
        :return: String
        """
        result = """\
installerHostName = '%(installerHostName)s'
installerIpAddress = %(installerIp)s
port = %(adminport)d
cfmUser = '%(cfmuser)s'
cfmPassword = '%(cfmpassword)s'

# DNS resolution settings
override_dns_domain = %(override_dns_domain)s
dns_options = %(dns_options)s
dns_search = %(dns_search)s
dns_nameservers = %(dns_nameservers)s
""" % settings_dict

        return result

    def __get_user_data(self, config, node=None):
        """
        Compile the cloud-init script from
        bootstrap template and encode into
        base64.

        :param config: Dictionary
        :param node: Node instance
        :return: String
        """
        self.getLogger().info(
            'Using cloud-init script template [%s]' % (
                config['user_data_script_template']))

        settings_dict = self.__get_common_user_data_settings(config, node)

        with open(config['user_data_script_template']) as fp:
            result = ''

            for line in fp.readlines():
                if line.startswith('### SETTINGS'):
                    result += self.__get_common_user_data_content(
                        settings_dict)
                else:
                    result += line

        combined_message = MIMEMultipart()

        if node and not config['use_instance_hostname']:
            # Use cloud-init to set fully-qualified domain name of instance
            cloud_init = """#cloud-config

fqdn: %s
""" % node.name

            sub_message = MIMEText(
                cloud_init, 'text/cloud-config', sys.getdefaultencoding())
            filename = 'user-data.txt'
            sub_message.add_header(
                'Content-Disposition',
                'attachment; filename="%s"' % filename)
            combined_message.attach(sub_message)

            sub_message = MIMEText(
                result, 'text/x-shellscript', sys.getdefaultencoding())
            filename = 'bootstrap.py'
            sub_message.add_header(
                'Content-Disposition',
                'attachment; filename="%s"' % filename)
            combined_message.attach(sub_message)

            return b64encode(str(combined_message).encode()).deocde()

        # Fallback to default behaviour
        return b64encode(result.encode()).decode()

    def deleteNode(self, dbNodes):
        """
        Delete a node from the infrastructure.

        :param dbNodes: List Nodes object
        :return: None
        """
        self._async_delete_nodes(dbNodes)

        self.getLogger().info(
            '%d node(s) deleted' % (
                len(dbNodes))
        )

    def _wait_for_instance_state(self, instance_ocid, state, callback=None,
                                 timeout=None):
        """
        Wait for instance to reach state

        :param instance_ocid: Instance OCID
        :param state: Expected state of instance
        :param timeout: (optional) operation timeout
        :return: None
        """
        # TODO: implement timeout
        for nRetries in itertools.count(0):
            instance = self.__client.get_instance(instance_ocid)

            if instance.data.lifecycle_state == state:
                break

            if callback:
                # Only call the callback if the requested state hasn't yet been
                # reached
                callback(instance_ocid, instance.data.lifecycle_state)

            gevent.sleep(get_random_sleep_time(retries=nRetries) / 1000.0)

    def _delete_node(self, node):
        # TODO: add error handling; if the instance termination request
        # fails, we shouldn't be removing the node from the system
        try:
            instance_cache = self.instanceCacheGet(node.name)

            # TODO: what happens when you attempt to terminate an already
            # terminated instance? Exception?
            instance = self.__client.get_instance(instance_cache['id'])

            logadapter = CustomAdapter(
                self.getLogger(), {'instance_ocid': instance_cache['id']})

            # Issue terminate request
            logadapter.debug('Terminating...')

            self.__client.terminate_instance(instance.data.id)

            # Wait 3 seconds before checking state
            gevent.sleep(3)

            # Wait until state is 'TERMINATED'
            self._wait_for_instance_state(instance_cache['id'], 'TERMINATED')

            # Clean up the instance cache.
            self.instanceCacheDelete(node.name)
        except ResourceNotFound:
            pass

        # Remove Puppet certificate
        bhm = osUtility.getOsObjectFactory().getOsBootHostManager()
        bhm.deleteNodeCleanup(node)

    def __get_installer_ip(self, hardwareprofile=None):
        """
        Get IP address of the installer node.

        :param hardwareprofile: Object
        :return: String ip address
        """
        if self.__installer_ip is None:
            if hardwareprofile and hardwareprofile.nics:
                self.__installer_ip = hardwareprofile.nics[0].ip
            else:
                self.__installer_ip = self.installer_public_ipaddress

        return self.__installer_ip

    @staticmethod
    def __get_encoded_list(items):
        """
        Return Python list encoded in a string.

        :param items: List
        :return: String
        """
        return '[' + ', '.join(['\'%s\'' % item for item in items]) + ']' \
            if items else '[]'


class CustomAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return 'Instance OCID [...%s]: %s' % (
            self.extra['instance_ocid'][-6:], msg), kwargs
