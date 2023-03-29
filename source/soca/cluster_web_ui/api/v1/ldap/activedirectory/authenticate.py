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
import os.path

from flask_restful import Resource, reqparse
import config
import ldap
import errors
from decorators import private_api
from requests import post
import logging

logger = logging.getLogger("api")

class Authenticate(Resource):
    @private_api
    def post(self):
        """
        Validate a LDAP user/password
        ---
        tags:
          - LDAP management

        parameters:
          - in: body
            name: body
            schema:
              required:
                - user
                - password
              properties:
                user:
                  type: string
                  description: SOCA user
                token:
                  type: string
                  description: Token associated to the user

        responses:
          200:
            description: Pair of user/token is valid
          210:
            description: Invalid user/token pair
          400:
            description: Client error
          401:
            description: Un-authorized
          500:
            description: Backend error
        """
        parser = reqparse.RequestParser()
        parser.add_argument("user", type=str, location='form')
        parser.add_argument("password", type=str, location='form')
        args = parser.parse_args()
        user = args["user"]
        password = args["password"]
        if user is None or password is None:
            return errors.all_errors('CLIENT_MISSING_PARAMETER', "user (str) and password (str) are required.")

        try:
            ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, config.Config.CERT_FILE)
            ldap.set_option(ldap.OPT_DEBUG_LEVEL, 255)
            conn = ldap.initialize(config.Config.LDAP_URL)
            conn.simple_bind_s(f"{user}@{config.Config.DOMAIN_NAME}", password)
            logger.info(f"Auth success")
            self.create_user_intermedia_info(user)
            return {'success': True, 'message': 'User is valid'}, 200
        except Exception as err:
            logger.info(f"Auth failed: {str(err)}")
            return errors.all_errors(type(err).__name__, err)

    def create_user_intermedia_info(self, username):
        home = f"{config.Config.USER_HOME}/{username}"
        if os.path.exists(home):
            return {'success': True, 'message': 'User home is existed'}
        try:
            logger.info(f"About to generate API KEY for {username}")
            # Create API Key
            post(config.Config.FLASK_ENDPOINT + "/api/user/api_key",
                headers={"X-SOCA-TOKEN": config.Config.API_ROOT_KEY},
                params={"user": username},
                verify=False).json()  # nosec
        except Exception as err:
            logger.error(
                "User created but unable to create API key. SOCA will try to generate it when user log in for the first time " + str(
                    err))