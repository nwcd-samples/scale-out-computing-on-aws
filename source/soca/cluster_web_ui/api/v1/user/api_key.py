######################################################################################################################
#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.                                                #
#                                                                                                                    #
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance    #
#  with the License. A copy of the License is located at                                                             #
#                                                                                                                    #
#      http://www.apache.org/licenses/LICENSE-2.0                                                                    #
#                                                                                                                    #
#  or in the 'license' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES #
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions    #
#  and limitations under the License.                                                                                #
######################################################################################################################

from flask_restful import Resource, reqparse
from models import db, ApiKeys
from requests import get
import datetime
import secrets
import config
from decorators import restricted_api, admin_api, retrieve_api_key
import errors
import logging
import sys
import shutil
import datetime
from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend as crypto_default_backend
import os

logger = logging.getLogger("api")


class ApiKey(Resource):
    @retrieve_api_key
    def get(self):
        """
        Retrieve API key of the user
        ---
        tags:
          - User Management
        parameters:
          - in: body
            name: body
            schema:
              required:
                - user
              properties:
                user:
                  type: string
                  description: user of the SOCA user

        responses:
          200:
            description: Return the token associated to the user
          203:
            description: No token detected
          400:
            description: Malformed client input
        """
        parser = reqparse.RequestParser()
        parser.add_argument("user", type=str, location='args')
        args = parser.parse_args()
        user = args["user"]
        if user is None:
            return errors.all_errors("CLIENT_MISSING_PARAMETER", "user (str) parameter is required")

        try:
            check_existing_key = ApiKeys.query.filter_by(user=user,
                                                         is_active=True).first()
            if check_existing_key:
                return {"success": True, "message": check_existing_key.token}, 200
            else:
                try:
                    # Create an API key for the user if needed
                    user_exist = get(config.Config.FLASK_ENDPOINT + "/api/ldap/user",
                                     headers={"X-SOCA-TOKEN": config.Config.API_ROOT_KEY},
                                     params={"user": user},
                                     verify=False) # nosec
                    if user_exist.status_code == 200:
                        api_key = self.post(config.Config.FLASK_ENDPOINT + "/api/ldap/user",
                                     headers={"X-SOCA-TOKEN": config.Config.API_ROOT_KEY},
                                     params={"user": user},
                                     verify=False)
                        if api_key.status_code == 200:
                            return {"success": True,
                                    "message": api_key.message}, 200
                        return {"success": False,
                                "message": "Fail to generate api token"}, 405
                    else:
                        return {"success": False,
                                "message": "Not authorized"}, 401

                except Exception as err:
                    logger.error(f"When retrieving api token occurred error {str(err)}")
                    return errors.all_errors(type(err).__name__, err)

        except Exception as err:
            logger.error(f"When retrieving api token occurred error {str(err)}")
            return errors.all_errors(type(err).__name__, err)

    @retrieve_api_key
    def post(self):
        """
        create new api key for AD user
        """
        parser = reqparse.RequestParser()
        parser.add_argument("user", type=str, location='args')
        args = parser.parse_args()
        user = args["user"]
        if user is None:
            return errors.all_errors("CLIENT_MISSING_PARAMETER", "user (str) parameter is required")
        try:
            permissions = get(config.Config.FLASK_ENDPOINT + "/api/ldap/sudo",
                              headers={"X-SOCA-TOKEN": config.Config.API_ROOT_KEY},
                              params={"user": user},
                              verify=False)  # nosec

            if permissions.status_code == 200:
                scope = "sudo"
            else:
                scope = "user"
            api_token = secrets.token_hex(16)
            new_key = ApiKeys(user=user,
                              token=api_token,
                              is_active=True,
                              scope=scope,
                              created_on=datetime.datetime.utcnow())
            db.session.add(new_key)
            db.session.commit()
            logger.info(f"API key generated for user {user}, the key is {api_token}")
            self.create_home(user)
            return {"success": True,
                    "message": api_token}, 200
        except Exception as err:
            logger.error(f"When generating api key occurred error {str(err)}")
            return errors.all_errors(type(err).__name__, err)

    def create_home(self, username):
        try:
            user_home = config.Config.USER_HOME
            logger.info(f"About to create home dir {user_home} for user {username} ")
            if os.path.exists(f"{user_home}/{username}"):
                logger.warning(f"Home is existed")
                return True
            key = rsa.generate_private_key(backend=crypto_default_backend(), public_exponent=65537, key_size=2048)
            private_key = key.private_bytes(
                crypto_serialization.Encoding.PEM,
                crypto_serialization.PrivateFormat.TraditionalOpenSSL,
                crypto_serialization.NoEncryption())
            public_key = key.public_key().public_bytes(
                crypto_serialization.Encoding.OpenSSH,
                crypto_serialization.PublicFormat.OpenSSH
            )
            private_key_str = private_key.decode('utf-8')
            public_key_str = public_key.decode('utf-8')
            # Create user directory structure
            user_path = f"{user_home}/{username}/.ssh"
            os.makedirs(user_path)

            # Copy default .bash profile
            shutil.copy('/etc/skel/.bashrc', f'{"/".join(user_path.split("/")[:-1])}/')
            shutil.copy('/etc/skel/.bash_profile', f'{"/".join(user_path.split("/")[:-1])}/')
            shutil.copy('/etc/skel/.bash_logout', f'{"/".join(user_path.split("/")[:-1])}/')

            # Create SSH keypair
            print(private_key_str, file=open(user_path + '/id_rsa', 'w'))
            print(public_key_str, file=open(user_path + '/id_rsa.pub', 'w'))
            print(public_key_str, file=open(user_path + '/authorized_keys', 'w'))

            # In SOCA original design, when creating new ldap user, its group name will be appended
            # socagroup to identify the user is produced by SOCA. So it's required to create the group first
            # and then change the owner to this group. However, the logic makes no sense in Microsoft AD case
            # Because we don't allow to manager AD objects like user or group in SOCA side,
            # it will disrupt customer own AD structure. The only exception is SOCA admin user can manager these objects
            # If there need to identify SOCA user, we can use /data/home/ path, since all SOCA users will be placed in it
            # Adjust file/folder ownership
            # for path in [f"{user_home}/{username}",
            #              f"{user_home}/{username}/.ssh",
            #              f"{user_home}/{username}/.ssh/authorized_keys",
            #              f"{user_home}/{username}/.ssh/id_rsa",
            #              f"{user_home}/{username}/.ssh/id_rsa.pub",
            #              f"{user_home}/{username}/.bashrc",
            #              f"{user_home}/{username}/.bash_profile",
            #              f"{user_home}/{username}/.bash_logout"]:
            #     # please make sure the usergroup is existed already on SOCA scheduler
            #     shutil.chown(path, user=username, group=usergroup)

            # Adjust file/folder permissions
            os.chmod(f"{user_home}/{username}", 0o700)
            os.chmod(f"{user_home}/{username}/.ssh", 0o700)
            os.chmod(f"{user_home}/{username}/.ssh/id_rsa", 0o600)
            os.chmod(f"{user_home}/{username}/.ssh/authorized_keys", 0o600)
            return True

        except Exception as e:
            logger.error(f"When creating home directory for user {username} occurred error {str(e)}")
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
            return False

    @restricted_api
    def delete(self):
        """
        Delete API key(s) associated to a user
        ---
        tags:
          - User Management
        parameters:
            - in: body
              name: body
              schema:
                required:
                  - user
                properties:
                    user:
                        type: string
                        description: user of the SOCA user

        responses:
            200:
                description: Key(s) has been deleted successfully.
            203:
                description: Unable to find a token.
            400:
               description: Client error.
        """
        parser = reqparse.RequestParser()
        parser.add_argument('user', type=str, location='form')
        args = parser.parse_args()
        user = args["user"]
        if user is None:
            return errors.all_errors("CLIENT_MISSING_PARAMETER", "user (str) parameter is required")
        try:
            check_existing_keys = ApiKeys.query.filter_by(user=user, is_active=True).all()
            if check_existing_keys:
                for key in check_existing_keys:
                    key.is_active = False
                    key.deactivated_on = datetime.datetime.utcnow()
                    db.session.commit()
                user_home = config.Config.USER_HOME
                if os.path.exists(f"{user_home}/{user}"):
                    try:
                        os.removedirs(f"{user_home}/{user}")
                    except IOError as ioe:
                        logger.warning(f"When removing path {user_home}/{user}, occurred error {str(ioe)}")
                return {"success": True, "message": "Successfully deactivated"}, 200
            else:
                return errors.all_errors("NO_ACTIVE_TOKEN")
        except Exception as err:
            logger.error(f"When deleting user {user_home}, occurred error {str(err)}")
            return errors.all_errors(type(err).__name__, err)
