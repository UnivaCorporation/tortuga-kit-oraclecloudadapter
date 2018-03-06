# About This Guide

This guide describes how to deploy a Tortuga 6 installer node on Oracle Cloud Infrastructure (OCI) and operate a cluster.  The guide assumes you're using the web console but all the primitives will apply across OCI APIs.

# Prerequisites

An OCI account.  Log into the web console to get the following.

Your tenancy ID; this is an `OCID` string that begins with `ocid1.tenancy` and can be found by clicking your tenancy name in the top left of the web console.

A Compartment ID; this is an `OCID` string that begins with `ocid1.compartment` and can be found by clicking `Identity` > `Compartments`.

Your user ID; this is an `OCID` string that begins with `ocid1.user` and can be found by clicking `Identity` > `Users`.

Have the built Tortuga package (i.e. `tortuga-*.tar.bz2`).  The source can be found at [https://github.com/UnivaCorporation/tortuga](https://github.com/UnivaCorporation/tortuga).

Have the Oracle Cloud Adapter kit package (i.e. `kit-oraclecloudadapter-*.tar.bz2`).  The source can be found at [https://github.com/UnivaCorporation/tortuga-kit-oraclecloudadapter](https://github.com/UnivaCorporation/tortuga-kit-oraclecloudadapter).

In this guide, we'll also install Univa Grid Engine via the `kit-uge-*.tar.bz2` kit.  A free trial can be found at [http://www.univa.com/resources/univa-navops-launch-trial-kits.php](http://www.univa.com/resources/univa-navops-launch-trial-kits.php).

# Navops Launch

If you are interested in using Tortuga in production and you require support or add-ons then Univa is providing a productized version of Tortuga under the name [Navops Launch](http://univa.com/products) together with support options, services and integrated products.

# Installer Node

These steps will get your installer node up and running.

## Virtual Cloud Network

We need to create a Virtual Cloud Network (VCN) to allow your installer nodes to communicate with your compute nodes.

Navigate to the VCN overview page by clicking `Networking` > `Virtual Cloud Networks`.

Click `Create virtual cloud network`.

Choose the correct compartment to create this VCN in.

Name the VCN.

Select `Create virtual cloud network plus related resources` unless you want to create the VCN resources yourself (this guide won't cover that scope).

Complete the creation by clicking `Create virtual cloud network`.

*This will create a subnet for each availability domain*

### Configuring the Subnet Security

We need to allow free communication between nodes in the subnet.  To add this rule, click `Networking` > `Virtual Cloud Networks`.  Click on the VCN created previously.  You'll be presented with a list of subnets, one for each availability domain.  For each of these, click in the `Default security list` and do the following.

When viewing the security list, click `Edit all rules`.  In the `Allow rules for ingress` section, click `Add rule`.  In the newly inserted row, change the `IP protocol` to `All protocols`, then set the `source CIDR` to the subnet address (e.g. `10.0.0.0/16`).

Finish by clicking `Save security list rules`.

## Creating Installer Instance

We're now ready to launch the installer instance.

Navigate to the Instances overview page by clicking `Compute` > `Instances`.

Check that the compartment is set correctly in the drop down menu to the left.

Click `Launch instance`.

Name the instance.

Select an availability domain.

Select an operating system image.  We currently support `CentOS 7` and `Oracle Linux 7`.

Choose a shape (aka instance type).  We recommend `VM.Standard.1.4`.
*You are able to use a virtual machine installer to deploy bare metal machines.*

Select the VCN created previously.

Select the subnet created previously.

Upload or paste the SSH public key of the machine you will SSH from.

Click `Launch instance`.

## Configuring the Installer Instance

### Install Tortuga

You'll then be redirected to the instance overview.  Once the instance has been provisioned, you'll be given a public IP address.

Copy the prerequisites packages onto the installer node, into `opc`'s home directory.

```
scp tortuga-*.tar.bz2 opc@${INSTANCE_PUBLIC_IP}:~/
scp kit-oraclecloudadapter-*.tar.bz2 opc@${INSTANCE_PUBLIC_IP}:~/
scp kit-uge-*.tar.bz2 opc@${INSTANCE_PUBLIC_IP}:~/
```

Using the public IP, SSH into the instance using the `opc` user.

```
ssh opc@${INSTANCE_PUBLIC_IP}
```

Elevate yourself to `root` and set SELinux to `permissive`.

```
sudo su -
setenforce 0
sed -i 's/SELINUX=enforcing/SELINUX=permissive/g' /etc/selinux/config
```

Open the following firewall ports.

| Port | Protocol | Description |
|------:|:--------:|------------------------------------------------------------------|
| 22 | tcp | SSH
| 53 | udp/tcp | DNS (installer) |
| 67 | udp/tcp | DHCP (only req'd for on-premise node provisioning) (installer) |
| 68 | udp/tcp | DHCP (only req'd for on-premise node provisioning) (installer) |
| 111 | udp/tcp | rpcbind (req'd for NFS) |
| 1194 | udp/tcp | OpenVPN (only required when using point-to-point VPN; installer) |
| 2049 | udp/tcp | NFS (installer) |
| 6444 | tcp | Grid Engine qmaster (installer) *default* |
| 6445 | tcp | Grid Engine execd (compute) *default* |
| 8008 | tcp | Tortuga "internal" web server (installer) |
| 8140 | tcp | Puppet server (installer) |
| 8443 | tcp | Tortuga web service (installer) |
| 61614 | tcp |ActiveMQ (req'd by MCollective (installer) |

```
firewall-cmd --permanent --zone=public --add-port=[port]/{udp,tcp}
```

Unpack the Tortuga package.

```
cd ~opc
tar -xjf tortuga-*.tar.bz2
cd tortuga-*
```

Run the installer

```
./install-tortuga.sh
/opt/tortuga/bin/tortuga-setup --defaults
source /opt/tortuga/etc/tortuga.sh
```

### Upload Installer PEM key

In order for the installer to interact with OCI, we need to give OCI the Installer's public key in PEM format.

Click your email address in the top right of the web console, then `User Settings`.  Make sure `API Keys` is selected to the left and click `Add public key`.  Acquire the PEM formatted public key.

```
openssl rsa -in ~/.ssh/id_rsa -outform pem -pubout
```

Copy the output and paste it into the window on the web console.  The fingerprint given will be needed in the `Configure the Adapter` section.

### Configure DNS

To allow Tortuga to set the hostnames of added compute nodes, we need to enable the DNS component.

```
enable-component -p dns
```

### Create Software Profile

This software profile will be used to represent compute nodes in the cluster. The software profile name can be arbitrary.

```
create-software-profile --name execd --no-os-media-required
```

### Create Hardware Profile

This hardware profile will used to represent compute nodes in the cluster. The hardware profile name is arbitrary.

```
create-hardware-profile --name execd
```

### Map the Software and Hardware Profile

Profiles must be mapped in order for Tortuga to identify a valid compute node provisioning configuration.

```
set-profile-mapping --software-profile execd --hardware-profile execd
```

### Install the Oracle Cloud Adapter

We're now ready to install the OCI adapter via the kit.

```
install-kit ~opc/kit-oraclecloudadapter-*.tar.bz2
```

Then we can enable it.  At the time of writing this guide, the version is `6.3.0`.

```
enable-component -p oraclecloudadapter-6.3.0-0 management-6.3
```

### Configure the Adapter

Now we can create an instance of the adapter, whilst passing the settings.

```
adapter-mgmt create \
    --resource-adapter oraclecloud \
    --profile default \
    --setting availability_domain=<Availability domain name> \
    --setting compartment_id=<Compartment OCID> \
    --setting shape=<Shape name> \
    --setting subnet_id=<Subnet OCID> \
    --setting image_id=<OS Image OCID> \
    --setting region=<Region name> \
    --setting tenancy=<Tenancy OCID> \
    --setting user=<User OCID> \
    --setting fingerprint=<API key fingerprint>
```

### Create Hardware Profile for Compute Nodes

```
create-hardware-profile --name execd-oci
update-hardware-profile --name execd-oci --resource-adapter oraclecloud --location remote
```

Then map this to the software profile.

```
set-profile-mapping --software-profile execd --hardware-profile execd-oci
```

### Install UGE Kit

This can be skipped if the goal isn't a Univa Grid Engine cluster.

```
install-kit ~opc/kit-uge*.tar.bz2
```

Configure the UGE cluster.

```
uge-cluster create default
uge-cluster update default --add-qmaster-swprofile Installer
uge-cluster update default --var sge_cell_netpath="%(qmaster)s:%(sge_root)s/%(cell_name)s"
uge-cluster update default --var manage_nfs=false
```

Enable the qmaster component.

```
enable-component -p qmaster
```

Then source the UGE environment.

```
source /opt/uge-*/default/common/settings.sh
```

We need to create an NFS mount to share with the compute nodes.

```
echo "/opt/uge-8.5.4 *(rw,async)" >> /etc/exports
exportfs -a
systemctl restart nfs
```

Enable the execd component with the software profile.

```
enable-component --software-profile execd execd
```

## Add Compute Nodes

We're now ready to add nodes to the cluster.

```
add-nodes --count 3 --software-profile execd --hardware-profile execd-oci
```

You can view the list of nodes.

```
get-node-list
```

If you chose to follow the UGE install, you can also see the nodes in the cluster.

```
qhost
```
