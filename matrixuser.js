import { check } from 'k6';
import http from 'k6/http';
fs = require('fs');

let tokensDict = {};

if(fs.existsSync('users.csv')) {

  let data = fs.readFileSync('users.csv', 'utf8');

  let rows = data.split('\n');
  let headers = rows[0].split(',');
  rows.shift(); 

  rows.forEach(row => {
    let fields = row.split(',');
    let item = {};

    headers.forEach((header, i) => {
      item[header] = fields[i];
    });

    tokens[item.username] = item;
    delete item.username;
  });

}

let users = [];

function updateTokens(msg) {
  // var tokensDict = {};
  username = msg.username
  user_id = msg.user_id
  access_token = msg.access_token
  sync_token = msg.sync_token
  tokensDict[username] = { 
                "user_id": user_id, 
                "access_token": access_token,
                "sync_token": sync_token }
  console.log(tokensDict)
}

export class MatrixUser {

  constructor() {
    this.matrixVersion = 'v3';
    this.username = null;
    this.password = null;
    this.user_id = null;
    this.access_token = null;
    this.device_id = null;
    this.matrix_domain = null;
    this.sync_timeout = 30;

    this.resetUserState();
  }

  resetUserState() {
    this.invited_room_ids = new Set([]);
    this.joined_room_ids = new Set([]);

    this.room_avatar_urls = {};
    this.user_avatar_urls = {};
    this.earliest_sync_tokens = {};
    this.room_display_names = {};
    this.user_display_names = {};
    this.media_cache = {};

    this.recent_messages = {};
    this.current_room = null;

    this.sync_token = null;
    this.initial_sync_token = null;
    this.matrix_sync_task = null;
  }

  register() {
    const url = `/matrix/client/${this.matrix_version}/register`;

    const requestBody = {
      username: this.username,
      password: this.password,
      inhibit_login: false,
    };

    const registerResponse = http.post( url, requestBody, {
      headers: { 'Content-Type': 'application/json' },
    });
  
    check(registerResponse, {
      'Register Status is 200': (r) => r.status === 200,
    });


    if (registerResponse.status === 200) {
      console.log(`User [${this.username}] Success! Didn't even need UIAA!`);
      const registerData = JSON.parse(registerResponse.body);

      const user_id = registerData.user_id;
      const access_token = registerData.access_token;

      if (!user_id || !access_token) {
        console.error(`User [${this.username}] Failed to parse /register response!\nResponse: ${registerResponse.body}`);
        return;
      }
    } else if (registerResponse.status === 401) {
      console.log(`User [${this.username}] Handling UIAA flow`);

      const flows = JSON.parse(registerResponse.body).flows;

      if (!flows || flows.length === 0) {
        console.error(`User [${this.username}] No UIAA flows for /register\nResponse: ${registerResponse.body}`);
        return;
      }

      // FIXME: Currently we only support dummy auth
      // TODO: Add support for MSC 3231 registration tokens
      requestBody.auth = {
        type: 'm.login.dummy',
      };

      const session_id = registerData.session;

      if (session_id) {
        requestBody.auth.session = session_id;
      }

      const response2 = http.post(registerUrl, requestBody, {
        headers: { 'Content-Type': 'application/json' },
      });

      check(response2, {
        'Register Status is 200 or 201': (r) => r.status === 200 || r.status === 201,
      });

      if (response2.status === 200 || response2.status === 201) {
        console.log(`User [${this.username}] Success!`);
        const response2Data = JSON.parse(response2.body);

        const user_id = response2Data.user_id;
        const access_token = response2Data.access_token;

        if (!user_id || !access_token) {
          console.error(`User [${this.username}] Failed to parse /register response!\nResponse: ${response2.body}`);
        }
      } else {
        console.error(`User [${this.username}] /register failed with status code ${response2.status}\nResponse: ${response2.body}`);
      }
    } else {
      console.error(`User [${this.username}] /register failed with status code ${registerResponse.status}\nResponse: ${registerResponse.body}`);
    }
  }

  login_from_csv(user_dict) {
    this.username = user_dict["username"]
    this.password = user_dict["password"]

    if (!tokensDict[this.username]) {
      this.user_id = null;
      this.access_token = null;
      this.sync_token = null;
    } else {
      this.user_id = tokensDict[this.username]?.user_id;
      this.access_token = tokensDict[this.username]?.access_token;
      this.sync_token = tokensDict[this.username]?.sync_token;
  
      // Handle empty strings
      if (this.user_id.length < 1 || this.access_token.length < 1) {
        this.user_id = null;
        this.access_token = null;
        return;
      }
  
      if (this.sync_token.length < 1) {
        this.sync_token = null;
      }
  
      this.matrix_domain = this.user_id.split(":").slice(-1)[0];
    }
  
    this.resetUserState();
  }

  login(start_syncing = false, log_request = false) {
    if (!this.username || !this.password) {
      console.error("No username or password");
      return;
    }

    this.resetUserState();
  
    const url = `/_matrix/client/${this.matrix_version}/login`;
    
    const body = {
      type: "m.login.password",
      identifier: {
        type: "m.id.user",
        user: this.username,
      },
      password: this.password,
    };

    try {
        const requestArgs = { method: "POST", url: url, json: body };

        const request = log_request ? this.rest : this.client.request;
        requestArgs.catch_response = !log_request;
    
        const response = request(requestArgs);

        // const response = http.post(url, body, { json: body, tags: { name: 'login' }});

        check(response, {
            'Login Status is 200': (r) => r.status === 200,
        });

        const responseJson = response.json();
        this.access_token = responseJson.access_token;
        this.user_id = responseJson.user_id;
        this.device_id = responseJson.device_id;
        this.matrix_domain = this.user_id.split(":").pop();

        // Refresh tokens stored in the csv file
        updateTokens({ data: { username: user.username, user_id: user.user_id, access_token: user.access_token, sync_token: "" } });

        if (start_syncing && this.access_token) {
            // Spawn a new VU to act as this user's client, constantly syncing with the server
            this.sync_timeout = 30;
            this.matrix_sync_task = setInterval(() => {
              this.sync_fo;
          }, 1000); 
            const syncInterval = 1; // seconds
            const iterations = syncTimeout / syncInterval;

            for (let i = 0; i < iterations; i++) {
                this.sync_forever();
            }
        }
    } catch (error) {
        console.error("Error during login:", error);
    }
  }

  set_displayname(displayname = null) {
    if (!this.user_id) {
        console.error(`User [${this.username}] Can't set displayname without a user id`);
        return;
    }

    let userNumber;

    if (displayname) {
        userNumber = this.username.split(".").pop();
        displayname = `User ${userNumber}`;
    }

    const url = `/_matrix/client/${this.matrix_version}/profile/${this.user_id}/displayname`;
    const label = `/_matrix/client/${this.matrix_version}/profile/_/displayname`;
    const body = {
        "displayname": displayname,
    };

    const response =  this.matrix_api_call("PUT", url, body, label)

    // const response = http.put(url, JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, tags: { name: 'setDisplayName' } });

    check(response, {
        'Set Display Name Status is 200': (r) => r.status === 200,
    });

    if ('error' in response.json()) {
        console.error(`User [${user.username}] failed to set displayname`);
    }

  }

  matrix_api_call(method, url, body = null, name_tag = null) {
    if (this.access_token) {
        console.warn(`API call to ${url} failed -- No access token`);
        return null;
    }

    const headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${this.access_token}`,
    };

    return http.request(method, url, { headers: headers, json: body, tags: { name: name_tag } });
  }

  sync_forever() {}


}

