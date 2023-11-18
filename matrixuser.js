import { check } from "k6";
import { SharedArray } from "k6/data";
import http from "k6/http";
import papaparse from "https://jslib.k6.io/papaparse/5.1.1/index.js";

import { FormData } from "https://jslib.k6.io/formdata/0.0.2/index.js";
// const fs = require('fs');
// import { someHelper } from './helper.js';

// export default function () {
//   someHelper();
// }

const csvData = new SharedArray("another data name", function () {
  return papaparse.parse(open("./users.csv"), { header: true }).data;
});

const imgAvatar = open("./avatar.png", "b");
// const binFile = open('./avatar.png', 'b');

const root_url = "http://localhost:6167/";
let tokensDict = {};

// if(fs.existsSync('users.csv')) {
//   let data = fs.readFileSync('users.csv', 'utf8');
//   let rows = data.split('\n');
//   let headers = rows[0].split(',');
//   rows.shift();
//   rows.forEach(row => {
//     let fields = row.split(',');
//     let item = {};
//     headers.forEach((header, i) => {
//       item[header] = fields[i];
//     });
//     tokens[item.username] = item;
//     delete item.username;
//   });
// }

let users = [];

function updateTokens(msg) {
  // var tokensDict = {};
  username = msg.username;
  user_id = msg.user_id;
  access_token = msg.access_token;
  sync_token = msg.sync_token;
  tokensDict[username] = {
    user_id: user_id,
    access_token: access_token,
    sync_token: sync_token,
  };
  console.log(tokensDict);
}

export class MatrixUser {
  constructor() {
    this.matrix_version = "v3";
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

  register(msg) {
    const url = `http://localhost:6167/_matrix/client/${msg.matrix_version}/register`;

    const requestBody = {
      username: msg.username,
      password: msg.password,
      inhibit_login: false,
    };

    const registerResponse = http.post(url, JSON.stringify(requestBody), {
      headers: { "Content-Type": "application/json" },
    });

    check(registerResponse, {
      "Register Status is 200": (r) => r.status === 200,
    });
    console.log(registerResponse.status);
    console.log(registerResponse.body);

    if (registerResponse.status === 200) {
      console.log(`User [${msg.username}] Success! Didn't even need UIAA!`);
      const registerData = JSON.parse(registerResponse.body);

      const user_id = registerData.user_id;
      const access_token = registerData.access_token;

      if (!user_id || !access_token) {
        console.error(
          `User [${msg.username}] Failed to parse /register response!\nResponse: ${registerResponse.body}`
        );
        return;
      }
    } else if (registerResponse.status === 401) {
      console.log(`User [${msg.username}] Handling UIAA flow`);

      const flows = JSON.parse(registerResponse.body).flows;

      if (!flows || flows.length === 0) {
        console.error(
          `User [${msg.username}] No UIAA flows for /register\nResponse: ${registerResponse.body}`
        );
        return;
      }

      // FIXME: Currently we only support dummy auth
      // TODO: Add support for MSC 3231 registration tokens
      requestBody.auth = {
        type: "m.login.dummy",
      };

      const session_id = JSON.parse(registerResponse.body).session;

      if (session_id) {
        requestBody.auth.session = session_id;
      }

      const response2 = http.post(url, JSON.stringify(requestBody), {
        headers: { "Content-Type": "application/json" },
      });

      check(response2, {
        "Register Status is 200 or 201": (r) =>
          r.status === 200 || r.status === 201,
      });

      if (response2.status === 200 || response2.status === 201) {
        console.log(`User [${msg.username}] Success!`);
        const response2Data = JSON.parse(response2.body);

        const user_id = response2Data.user_id;
        const access_token = response2Data.access_token;

        if (!user_id || !access_token) {
          console.error(
            `User [${msg.username}] Failed to parse /register response!\nResponse: ${response2.body}`
          );
        }
      } else {
        console.error(
          `User [${msg.username}] /register failed with status code ${response2.status}\nResponse: ${response2.body}`
        );
      }
    } else {
      console.error(
        `User [${msg.username}] /register failed with status code ${registerResponse.status}\nResponse: ${registerResponse.body}`
      );
    }
  }

  login_from_csv(user_dict) {
    this.username = user_dict["username"];
    this.password = user_dict["password"];

    if (!tokensDict[this.username]) {
      this.user_id = null;
      this.access_token = null;
      this.sync_token = null;
    } else {
      // this.user_id = tokensDict[this.username]?.user_id;
      // this.access_token = tokensDict[this.username]?.access_token;
      // this.sync_token = tokensDict[this.username]?.sync_token;
      this.user_id = tokensDict[this.username]
        ? tokensDict[this.username].user_id
        : null;
      this.access_token = tokensDict[this.username]
        ? tokensDict[this.username].access_token
        : null;
      this.sync_token = tokensDict[this.username]
        ? tokensDict[this.username].sync_token
        : null;

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
    this.username = "user.000001";
    this.password = "mbgL2vhpuzdLGVCd";

    if (!this.username || !this.password) {
      console.error("No username or password");
      return;
    }

    this.resetUserState();

    const url = `http://localhost:6167/_matrix/client/v3/login`;

    const body = {
      type: "m.login.password",
      identifier: {
        type: "m.id.user",
        user: this.username,
      },
      password: this.password,
    };

    try {
      // const requestArgs = {
      //   method: "POST",
      //   url: url,
      //   json: JSON.stringify(body),
      // };

      // const request = log_request ? this.rest : this.client.request;
      // requestArgs.catch_response = !log_request;

      // const response = request(requestArgs);
      const response = http.post(url, JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
      });
      // const response = http.post(url, body, { json: body, tags: { name: 'login' }});
      // console.log(response.status);
      check(response, {
        "Login Status is 200": (r) => r.status === 200,
      });

      const responseJson = JSON.parse(response.body);
      this.access_token = responseJson.access_token;
      this.user_id = responseJson.user_id;
      this.device_id = responseJson.device_id;
      this.matrix_domain = this.user_id.split(":").pop();
      // console.log(this.access_token);
      // console.log(this.user_id);
      const msg = {
        data: {
          username: this.username,
          user_id: this.user_id,
          access_token: this.access_token,
          sync_token: "",
        },
      };

      // Refresh tokens stored in the csv file
      updateTokens(msg);
      console.log(msg);
      // if (start_syncing && this.access_token) {
      //   // Spawn a new VU to act as this user's client, constantly syncing with the server
      //   this.sync_timeout = 30;
      //   this.matrix_sync_task = setInterval(() => {
      //     this.sync_fo;
      //   }, 1000);
      //   const syncInterval = 1; // seconds
      //   const iterations = syncTimeout / syncInterval;

      //   for (let i = 0; i < iterations; i++) {
      //     this.sync_forever();
      //   }
      // }
    } catch (error) {
      console.error("Error during login:", error);
    }
  }

  set_displayname(displayname = null) {
    if (!this.user_id) {
      console.error(
        `User [${this.username}] Can't set displayname without a user id`
      );
      return;
    }

    let userNumber;

    if (displayname === null) {
      userNumber = this.username.split(".").pop();
      displayname = `User ${userNumber}`;
    }

    const url = `http://localhost:6167/_matrix/client/v3/profile/${this.user_id}/displayname`;
    const label = `http://localhost:6167/_matrix/client/v3/profile/_/displayname`;
    const body = {
      displayname: displayname,
    };

    const response = this.matrix_api_call(
      "PUT",
      url,
      JSON.stringify(body),
      label
    );
    // const response = http.put(url, JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, tags: { name: 'setDisplayName' } });

    check(response, {
      "Set Display Name Status is 200": (r) => r.status === 200,
    });
    console.log(`Status: ${response.status} display name: ${displayname}`);

    if ("error" in response.json()) {
      console.error(`User [${this.username}] failed to set displayname`);
    }
  }

  matrix_api_call(method, url, body = null, name_tag = null) {
    console.log(`User id: ${this.user_id}  Access Token: ${this.access_token}`);
    if (this.access_token === null) {
      console.warn(`API call to ${url} failed -- No access token`);
      return null;
    }
    return http.request(method, url, body, {
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Authorization: `Bearer ${this.access_token}`,
      },
      tags: {
        name: name_tag ? name_tag : "noname",
      },
    });
  }

  async set_avatar_image(filename) {
    if (this.user_id === null) {
      console.error(
        `User [${this.username}] Can't set avatar image without a user id`
      );
      return;
    }
    const imgAvatar = open(`./${filename}`, "b");

    // Upload the file to Matrix
    // const mxc_url = await upload_matrix_media(data, mime_type);
    const mxc_url = await upload_matrix_media(imgAvatar);
    if (mxc_url === null) {
      console.error(`User [${this.username}] Failed to set avatar image`);
      return;
    }
    const url = `http://localhost:6167/_matrix/client/${this.matrix_version}/profile/${this.user_id}/avatar_url`;
    const body = JSON.stringify({
      avatar_url: mxc_url,
    });
    const label = `/_matrix/client/${this.matrix_version}/profile/_/avatar_url`;

    const response = this.matrix_api_call("POST", url, body, label);
    return response;
  }

  async upload_matrix_media(imgAvatar) {
    const url = `http://localhost:6167/_matrix/media/${this.matrix_version}/upload`;

    try {
      const data = {
        field: "png",
        file: http.file(imgAvatar, "test.bin"),
      };

      const response = http.post(url, data, {
        headers: {
          Authorization: `Bearer ${this.access_token}`,
        },
      });

      console.log(response.status);

      if (response.status === 200) {
        const responseData = response.json();
        return responseData.content_uri || null;
      } else {
        console.error(
          `User [${this.username}] Failed to upload media (HTTP ${response.status})`
        );
        return null;
      }
    } catch (error) {
      console.error(`Error uploading media: ${error}`);
      return null;
    }
  }
  createRoom(alias, roomName, userIds = []) {
    const url = `http://localhost:6167/_matrix/client/${this.matrix_version}/createRoom`;
    const requestBody = {
      preset: "private_chat",
      name: roomName,
      invite: userIds,
    };

    if (alias !== null) {
      requestBody.room_alias_name = alias;
    }

    try {
      const response = this.matrix_api_call(
        "POST",
        url,
        JSON.stringify(requestBody)
      );

      check(response, {
        "createRoom Status is 200": (response) => response.status === 200
      });

      const room_id = JSON.parse(response.body).room_id;
      if (room_id === null) {
        console.error(
          `User [${this.username}] Failed to create room for [${roomName}]`
        );
        console.error(`${response.error_code}: ${response.error}`);
        return null;
      } else {
        console.log(`User [${this.username}] Created room [${room_id}]`);
        return room_id;
      }
    } catch (error) {
      console.error(`An error occurred:${error}`);
      return null;
    }
    // Not sure how we might end up here, but just to be safe...
    // return null;
  }

  get_user_avatar_url(user_id) {
    const url = `http://localhost:6167/_matrix/client/v3/profile/${user_id}/avatar_url`;
    const label = `http://localhost:6167/_matrix/client/v3/profile/_/avatar_url`;

    try {
      const response = matrix_api_call("GET", url, null, label);
      const avatar_url = JSON.parse(response.body).avatar_url || null;
      this.user_avatar_urls[user_id] = avatar_url;
    } catch (error) {
      console.error(`Error fetching user's avatar URL: ${error}`);
    }
  }
  get_user_displayname(user_id) {
    const url = `http://localhost:6167/_matrix/client/v3/profile/${user_id}/displayname`;
    const label = `http://localhost:6167/_matrix/client/v3/profile/_/displayname`;

    try {
      const response = this.matrix_api_call("GET", url, null, label);
      const displayname = JSON.parse(response.body).displayname || null;
      this.user_display_names[user_id] = displayname;
      return displayname;
    } catch (error) {
      console.error(`Error fetching user's display name: ${error}`);
    }
  }

  loadRoomData(room_id) {
    // Load the avatars for recent users
    // Load the thumbnails for any messages that have one
    const messages = this.recent_messages[room_id] || [];

    for (const message of messages) {
      const senderUserId = message.sender;
      let senderAvatarMxc = this.user_avatar_urls[senderUserId];

      if (!senderAvatarMxc) {
        // Fetch the avatar URL for senderUserId
        senderAvatarMxc = get_user_avatar_url(senderUserId);
      }

      if (senderAvatarMxc && senderAvatarMxc.length > 0) {
        download_matrix_media(senderAvatarMxc);
      }

      let senderDisplayname = user_display_names[senderUserId];

      if (!senderDisplayname) {
        senderDisplayname = get_user_displayname(senderUserId);
      }
    }

    for (const message of messages) {
      const content = message.content;
      const msgtype = content.msgtype;

      if (["m.image", "m.video", "m.file"].includes(msgtype)) {
        const thumbMxc = content.thumbnail_url;

        if (thumbMxc) {
          download_matrix_media(thumbMxc);
        }
      }
    }
  }

  getRandomRoomId() {
    if (this.joined_room_ids.length > 0) {
      const roomIds = Array.from(this.joined_room_ids);
      const randomIndex = Math.floor(Math.random() * roomIds.length);
      return roomIds[randomIndex];
    } else {
      return null;
    }
  }

  joinRoom(roomId) {
    if (this.joined_room_ids.has(roomId)) {
      // Looks like we already joined. Peace out.
      return;
    }

    console.log(`User [${this.username}] joining room ${roomId}`);
    const url = `http://localhost:6167/_matrix/client/${this.matrix_version}/rooms/${roomId}/join`;
    const label = `http://localhost:6167/_matrix/client/${this.matrix_version}/rooms/_/join`;

    try {
      const response = this.matrix_api_call("POST", url, null, label);

      if (!response) {
        console.error(
          `User [${this.username}] Failed to join room ${roomId} - timeout`
        );
        return null;
      }

      check(response, {
        "joinRoom Status is 200": (r) => r.status === 200,
      });

      if ("room_id" in response.json()) {
        console.log(`User [${this.username}] Joined room ${roomId}`);
        this.joined_room_ids.add(roomId);
        this.invited_room_ids.delete(roomId);
        this.loadRoomData(roomId);
        return response.json().roomId;
      } else {
        console.warn(
          `User [${this.username}] Failed to join room ${roomId} - ${
            response.error_code || "???"
          }: ${response.error || "Unknown"}`
        );
        return null;
      }
    } catch (error) {
      console.error(`Error joining room: ${error}`);
      return null;
    }
  }

  setTyping(roomId, isTyping) {
    const url = `http://localhost:6167/_matrix/client/${this.matrix_version}/rooms/${roomId}/typing/${this.user_id}`;

    const body = JSON.stringify({
      timeout: 10 * 1000,
      typing: isTyping,
    });

    const label = `http://localhost:6167/_matrix/client/${this.matrix_version}/rooms/_/typing/_`;

    try {
      const response = this.matrix_api_call("PUT", url, body, label);

      check(response, {
        "setTyping Status is 200": (r) => r.status === 200
      });
    } catch (error) {
      console.error(`Error setting typing status: ${error}`);
    }
  }

  sendReadReceipt(roomId, eventId) {
    const url = `http://localhost:6167/_matrix/client/${this.matrix_version}/rooms/${roomId}/receipt/m.read/${eventId}`;
    const body = JSON.stringify({ "thread_id": "main" });
    const label = `http://localhost:6167/_matrix/client/${this.matrix_version}/rooms/_/receipt/m.read/_`;

    try {
      const response = this.matrix_api_call("POST", url, body, label);

      check(response, {
        "sendReadReceipt Status is 200": (r) => r.status === 200
      });
    } catch (error) {
      console.error(`Error sending read receipt: ${error}`);
    }
  }

  sync_forever() {}
}

const msg = {
  matrix_version: "v3",
  username: "user.000001",
  password: "mbgL2vhpuzdLGVCd",
};

const msg1 = {
  matrix_version: "v3",
  username: "user.000000",
  password: "nk8rIu7Hg5VCwrr9",
};
export default function testMatrixUser() {
  let user = new MatrixUser();
  let user_id_list = [
    "@user.000000:matrix.conduit.local",
    "@user.000001:matrix.conduit.local",
  ];
  // user.register(msg);
  // user.login();
  //user.set_displayname("hello1");
  //console.log(user.get_user_displayname("@user.000001:matrix.conduit.local"));
  // const room_id = user.createRoom(null, "localroom", user_id_list);
  // user.set_displayname("helloworld");
  // user.set_avatar_image("avatar.png")
  // user.upload_matrix_media();
  // user.joinRoom(room_id)
  // user.setTyping(room_id, true)
  // user.sendReadReceipt(room_id, "event_id")
  // user.loadRoomData(idroom)
  // user.getRandomRoomId()
}
// export default function () {
//   let matrixUser = new MatrixUser();
//   console.log(matrixUser)
//   return matrixUser.register(data)
// }

// export default function register() {
//   // const url = `/_matrix/client/${msg.matrix_version}/register`;
//   const url = `http://localhost:6167/_matrix/client/${msg.matrix_version}/register`;
//   // const url = "https://spec.matrix.org/v1.4/client-server-api/#post_matrixclientv3register"

//   const requestBody = {
//     username: "duyhungtran",
//     password: "nk8rIu7Hg5VCwrr9",
//     inhibit_login: false,
//   };

//   const registerResponse = http.post(url, JSON.stringify(requestBody), {
//     headers: { "Content-Type": "application/json" },
//   });

//   check(registerResponse, {
//     "Register Status is 200": (r) => r.status === 200,
//   });
//   console.log(registerResponse.status);
//   console.log(registerResponse.body);

//   if (registerResponse.status === 200) {
//     console.log(`User [${msg.username}] Success! Didn't even need UIAA!`);
//     const registerData = JSON.parse(registerResponse.body);

//     const user_id = registerData.user_id;
//     const access_token = registerData.access_token;

//     if (!user_id || !access_token) {
//       console.error(
//         `User [${msg.username}] Failed to parse /register response!\nResponse: ${registerResponse.body}`
//       );
//       return;
//     }
//   } else if (registerResponse.status === 401) {
//     console.log(`User [${msg.username}] Handling UIAA flow`);

//     const flows = JSON.parse(registerResponse.body).flows;

//     if (!flows || flows.length === 0) {
//       console.error(
//         `User [${msg.username}] No UIAA flows for /register\nResponse: ${registerResponse.body}`
//       );
//       return;
//     }

//     requestBody.auth = {
//       type: "m.login.dummy",
//     };

//     const session_id = JSON.parse(registerResponse.body).session;

//     if (session_id) {
//       requestBody.auth.session = session_id;
//     }

//     const response2 = http.post(url, JSON.stringify(requestBody), {
//       headers: { "Content-Type": "application/json" },
//     });

//     check(response2, {
//       "Register Status is 200 or 201": (r) =>
//         r.status === 200 || r.status === 201,
//     });

//     if (response2.status === 200 || response2.status === 201) {
//       console.log(`User [${msg.username}] Success!`);
//       const response2Data = JSON.parse(response2.body);

//       const user_id = response2Data.user_id;
//       const access_token = response2Data.access_token;

//       if (!user_id || !access_token) {
//         console.error(
//           `User [${msg.username}] Failed to parse /register response!\nResponse: ${response2.body}`
//         );
//       }
//     } else {
//       console.error(
//         `User [${msg.username}] /register failed with status code ${response2.status}\nResponse: ${response2.body}`
//       );
//     }
//   } else {
//     console.error(
//       `User [${msg.username}] /register failed with status code ${registerResponse.status}\nResponse: ${registerResponse.body}`
//     );
//   }
// }
