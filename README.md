# SOCA定制开发1.0版

## :book: 背景

Scale-Out Computing on AWS（简称SOCA）旨在帮助用户更加轻松部署和运行多环境下计算密集型工作流程的解决方案。该解决方案提供了基于AWS的类型丰富的计算资源，快速的网络骨干以及无限存储等功能。该方案提供了用户接口以及自动化工具使得用户可以创建自己的队列，资源调度，Amazon Machine Images（AMI），软件和库等。
基于该解决方案提供的丰富功能，并结合西云数据的用户需求，我们对该解决方案进行了定制开发，主要包括：
- 用户域环境的支持
- AMI的优化
- 资源统计的重构
- 优化数据传输成本

## :rocket: 架构
该版本的架构遵循AWS SOCA 2.7.2 的主体架构，并对局部设计进行了重构。下图是AWS SOCA的整体架构，您可以访问[官方页面](https://awslabs.github.io/scale-out-computing-on-aws/tutorials/install-soca-cluster/)查看更多信息


![image](https://user-images.githubusercontent.com/5533748/228729700-bbaa1c74-e5c3-40bc-b4c9-5ed20b5402d1.png)

架构采用AWS CloudFormation模版部署基础组件，AWS服务，操作系统以及管理软件。具体包括以下功能：
1. Amazon EC2 Auto Scaling 自动提供运行集群用户任务（如横向扩展计算作业）所需的资源
2. 解决方案采用Amazon Elastic File System（Amaozn EFS）作为持久存储，Amazon Simple Storage Service（Amazon S3）作为日志存储，以及可选的并行文件系统FSx for Lustre
3. 作为核心，Amazon Elastic Compute Cloud（Amazon EC2）实例实现了调度器，该调度器动态提供了用户任务所需的AWS资源，此外，调度器示例也实现了Web接口以便用户和管理员与之交互
4. 启动2D或3D工作站并使用NICE DCV（Desktop Cloud Visualization 桌面云可视化）来提交任务或者运行GUI
5. 使用包括AWS Secret Manager，AWS Certificate Manager，Securiry Group以及AWS Identity and Access Management（IAM）的安全服务和资源
6. 使用AWS Lambda函数来验证必备条件并为Application Load Lalancer（ALB）生成默认签名证书以管理DCV工作站访问会话
7. 使用Amazon OpenSearch Service集群来存储工作和主机信息。
8. 使用Elastic Load Balancing来保证跨可用区的访问，以及用于AWS Cost Explore的成本分析标签

> 注意：上述第7条是AWS Global的设计，由于OpenSearch的成本因素以及国内没有启用Congnito，我们对第7条进行了重构，该部分的架构如下：

![image](https://user-images.githubusercontent.com/5533748/228731256-4e2f89ae-350c-456c-ab41-8d0fda447f2c.png)

图的左侧是工作负载，它包括Scheduler，图形工作站，以及各种存储服务。其中Scheduler和图形工作站是Amazon EC2实例，它们分别用来调度和运行各种计算负责。存储服务包括Amazon ESB和Amazon S3。

图的中间部分是数据的收集、处理和保持。这部分，我们全面使用了亚马逊云科技的无服务器产品：

针对EC2实例：
- EventBridge用来接收和筛选实例的开关机等事件；
- SNS用来触发事件处理的函数；
- Lambda用来实现函数的具体逻辑；DynamoDB用来保存处理结果

针对EBS和S3：

由于存储用量的变化十分频繁，如果复用EventBridg的事件机制不仅导致相应的成本增加，而且对最终用户的作用也十分有限。所以这里采用了如下的轮训机制：
- CloudWatch用来定时触发数据采集和处理的函数；
- Lambda用来实现函数的具体逻辑；
- DynamoDB同样用来保存处理结果；这样做的好处是可以按需来调整采集数据的频率

最后我们看一下图右侧的可视化部分：我们使用EC2实例搭建了一个Web站点，并通过亚马逊云科技托管的负载均衡器Application Load Balancer将Web站点公开到互联网，便于终端用户查看监控信息。

## :pencil2: 安装
为了方便安装和部署，我们在Global版本的基础上做了大量优化工作，主要包括：
- 将下载和安装耗时的软件和系统依赖通过AMI的形式提前安装
- 将NodeJs和Python的镜像地址换成国内地址
- 将与安装路径相关的软件和依赖提前放置到SOCA源代码中

基于上述优化，整个安装过程在大幅提升稳定性的同时降低了安装时间。下面以OpenLDAP为例来演示安装过程

> 注意：当前版本只支持CDK方式安装，后续我们会推出CloudFormation安装版本。

### 前置条件
1. AWS中国区账号
 - 如果没有，请访问https://www.amazonaws.cn/ 进行免费注册
 - 建议您创建IAM账号来安装，关于如何创建IAM账号请参见附录1
2. 下载IAM账号的访问密钥
 - 如果未下载，请按照该链接https://docs.aws.amazon.com/zh_cn/powershell/latest/userguide/pstools-appendix-sign-up.html进行配置。
 - 注意：访问密钥只能被下载一次，请下载后妥善保管
3. 一台可连接互联网的Amazon Linux 2 EC2实例
 - 该类型实例已经默认安装了awscli，awscli是安装SOCA的必备软件
 - 您可以通过SSH工具来访问，访问前请确保EC2 KeyPair以及安全组正确设置。如何设置请参见附录2和3
4. 一个具有读写权限的S3桶
 - 该桶用来保存SOCA在安装过程产生的中间文件。请记住此桶的名称，在后面的安装过程中会用到
 - 如果想创建新桶，请参见附录4

### 安装

**步骤1:**

SOCA通过LDAP来管理用户，而LDAP在不同的平台上有着不同的实现：在Windows平台通过Microsoft AD来实现，在Linux平台通过OpenLDAP来实现。因此在安装之前必须通过配置文件来告诉SOCA在哪个平台上安装。可通过该路径找到配置文件：https://github.com/nwcd-samples/scale-out-computing-on-aws/blob/main/installer/default_config.yml
定位到81行会看到ldap相关配置

```
Configure your Directory options below
directoryservice:
  provider: "openldap" # openldap (recommended) or activedirectory
  openldap:
    name: "soca.local" # base DN for your OpenLDAP. SOCA will create 3 OUs: People, Group and Sudoers. Edit source/scripts/Scheduler.sh if you need to edit these OUs
  activedirectory:
    name: "soca.local" # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-directoryservice-microsoftad.html#cfn-directoryservice-microsoftad-name
    short_name: "SOCA" # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-directoryservice-microsoftad.html#cfn-directoryservice-microsoftad-shortname
    edition: "Standard" # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-directoryservice-microsoftad.html#cfn-directoryservice-microsoftad-edition
  # Base organizational unit distinguished name (DN), like OU=Marketing,DC=example,DC=com
  # if specify the base_ou, SOCA will access AD objects like person, organizationUint or group WITHIN it.
  # Or will use domain name as default like
  # run below powershell command in domain controller to get all organizational unit dn
  # Get-ADOrganizationalUnit -Filter 'Name -like "*"' | Format-Table Name, DistinguishedName -A
  base_ou: "OU=北京子公司,DC=yywad,DC=demo"
  # Your certification file(pem format) path on SOCA scheduler like /home/centos/sample.pem
  cert_file: "/home/centos/yywad_ca.pem"
  # When using security ldap connection, the ldap url is like ldaps://EC2AMAZ-RM14AV1.example.com:636
  # In above url, EC2AMAZ-RM14AV1.example.com is the certification user CN, you can run certutil command in AD controller
  # 636 is default security port
  # When using common ldap connection, the ldap url is domain name like ldap://example.com
  # Common ldap case is only for read operation on AD object, like list all AD users or groups
  # Security ldap case is suitable for read and write operation on AD object, like change AD password
  # You can specify the
  ldap_url: "ldaps://EC2AMAZ-RM14AV1.example.com:636"
```

其中：

- provider用来指定是openldap还是activedirectory，您可以根据实际场景来指定
- 当指定为openldap时，通过它的属性name来进一步指定openldap的根节点。
- 当指定为activedirectory，SOCA在安装时会自动判断当前AD是AWS 托管AD还是自建AD（程序通过判断directory_service_id来判断，该值为空则表示自建AD，否则表示托管AD）。如果是托管AD，SOCA会根据name，short_name和edition设置来自动创建托管AD。其中name代表domain name，short_name代表netbios name，edition代表AWS托管AD的类型，包括Standard和Enterprise
- 为了保证数据传输到的安全性，企业用户会搭建使用证书，因此当SOCA与LDAP实例建立连接时需要指定客户端证书的位置cert_file，以及安全链接地址ldap_url。
有时用户不想把整个树形结构完全暴露给客户端程序，此时通过指定base_ou来指定SOCA管理的范围，一旦指定该节点后，后续所有的ldap相关操作都只发生在该节点之下。注意，base_ou的值采用全路径格式，如：OU=北京子公司,DC=demo,DC=com

指定完上述参数后，该文件中的其他参数按照默认值即可安装

**步骤2:**

通过SSH工具连接到上面提到Amazon Linux2 EC2，然后执行下面的命令进行下载：
```
curl https://github.com/nwcd-samples/scale-out-computing-on-aws/archive/refs/heads/main.zip -o main.zip
```

**步骤3:**

解压后定位到installer目录，然后执行soca_installer.sh
注意：因为该脚本需要AWS AMI账号的权限，请确保您的访问密钥已经设置，具体设置请参考附录2
```
unzip main.zip
cd installer
./soca_installer.sh
```
脚本执行后会弹出如下界面

<img width="888" alt="image" src="https://user-images.githubusercontent.com/5533748/228741347-d5d4bad1-5e96-495a-b674-8971a6dbe9d9.png">

输入“yes”并回车启动安装，首先输入您期望的安装区域

<img width="888" alt="image" src="https://user-images.githubusercontent.com/5533748/228756426-f90c39f9-b90a-4a20-b146-e01b830d5a96.png">

请输入“cn-northwest-1”，这表示SOCA将在中国宁夏区安装。回车后会打开如下所示界面：

<img width="888" alt="image" src="https://user-images.githubusercontent.com/5533748/228761039-90028782-993a-4288-af18-09cfa486ac79.png">

SOCA会自动填充Scheduler的私网IP，如果填充失败可以手动收入。

<img width="888" alt="image" src="https://user-images.githubusercontent.com/5533748/228762734-c5959104-106d-4126-957b-db1e98c461fe.png">

然后依次指定如下参数：
1. SOCA集群名称：该名称自动以“SOCA-”开始，所以请不要在名称中包含“SOCA”字样。这里以roc为例，您可以指定您期望的名字，请不要包含特殊字符
2. S3桶的名字：输入您在必备阶段创建的S3桶名称
3. SOCA的管理员名称：请不要包含特殊字符，并且名称不能为admin
4. SOCA管理员密码及确认密码：密码不要包含@等特殊字符，因为可能根ldap中的关键字冲突。确认密码与密码要保持一致
5. SOCA Scheduler的操作系统，请输入centos7
6. SOCA Scheduler的密钥对，请输入您在必备阶段创建密钥对
7. SOCA集群运行的VPC：您可以选择“new”或者“existing”。New表示SOCA会创建一个新的VPC以及相应的子网；Existing表示SOCA安装到现有的VPC。这里输入“new”

继续输入如下参数

<img width="888" alt="image" src="https://user-images.githubusercontent.com/5533748/228767928-3b1681d2-8c0d-4de9-b0da-87d3a3457eed.png">

8. SOCA Scheduler的安全组：输入“new” 让SOCA自动创建
9. SOCA Scheduler的文件系统：输入“new” 让SOCA自动创建
10. SOCA Scheduler和计算节点的角色：输入“new” 让SOCA自动创建

指定完上述参数后SOCA开始安装，安装过程持续15分钟左右。安装完成后会看到如下信息

```
SOCA was installed successfully
SOCA Web Endpoint is https://soca-xxxx-viewer-xxxxxx.cn-northwest-1.elb.amazonaws.com.cn
```
将上面的Endpoint用浏览器打开即可看到SOCA界面。然后使用在安装过程中指定的SOCA管理员和密码即可完成登录。

## :palm_tree: 开发状态

### 当前版本功能
当前版本（SOCA定制开发1.0版）除了AWS Global功能外还包含如下功能：
1. 优化安装体验
2. 支持与Microsoft AD集成
3. 重构资源统计模块
4. 确保启动计算节点与Scheduler节点在同一个可用区

### 下一版本功能
1. CloudFormation版本支持
2. AMI优化

### 技术调研

根据某油气客户的反馈，在为某个项目进行计算时需要的输入数据高达20TB，计算完成后数据会存储一段时间然后释放。SOCA默认的存储是EBS，EBS具有低延迟和高吞吐量的特点，能够满足计算软件对高IO的需求，但EBS不具有弹性，这就导致较高的存储成本。为了兼顾高IO和弹性扩缩容的需求，需要进行重新架构。
