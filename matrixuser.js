import { check } from "k6";
import http from "k6/http";
import { json } from "stream/consumers";
fs = require("fs");

let tokensDict = {};

if (fs.existsSync("users.csv")) {
  let data = fs.readFileSync("users.csv", "utf8");

  let rows = data.split("\n");
  let headers = rows[0].split(",");
  rows.shift();

  rows.forEach((row) => {
    let fields = row.split(",");
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
  constructor(username = null, password = null) {
    this.matrix_version = "v3";
    this.username = username;
    this.password = password;
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

    const registerResponse = http.post(url, requestBody, {
      headers: { "Content-Type": "application/json" },
    });

    check(registerResponse, {
      "Register Status is 200": (r) => r.status === 200,
    });

    if (registerResponse.status === 200) {
      console.log(`User [${this.username}] Success! Didn't even need UIAA!`);
      const registerData = JSON.parse(registerResponse.body);

      const user_id = registerData.user_id;
      const access_token = registerData.access_token;

      if (!user_id || !access_token) {
        console.error(
          `User [${this.username}] Failed to parse /register response!\nResponse: ${registerResponse.body}`
        );
        return;
      }
    } else if (registerResponse.status === 401) {
      console.log(`User [${this.username}] Handling UIAA flow`);

      const flows = JSON.parse(registerResponse.body).flows;

      if (!flows || flows.length === 0) {
        console.error(
          `User [${this.username}] No UIAA flows for /register\nResponse: ${registerResponse.body}`
        );
        return;
      }

      // FIXME: Currently we only support dummy auth
      // TODO: Add support for MSC 3231 registration tokens
      requestBody.auth = {
        type: "m.login.dummy",
      };

      const session_id = registerData.session;

      if (session_id) {
        requestBody.auth.session = session_id;
      }

      const response2 = http.post(registerUrl, JSON.stringify(requestBody), {
        headers: { "Content-Type": "application/json" },
      });

      check(response2, {
        "Register Status is 200 or 201": (r) =>
          r.status === 200 || r.status === 201,
      });

      if (response2.status === 200 || response2.status === 201) {
        console.log(`User [${this.username}] Success!`);
        const response2Data = JSON.parse(response2.body);

        const user_id = response2Data.user_id;
        const access_token = response2Data.access_token;

        if (!user_id || !access_token) {
          console.error(
            `User [${this.username}] Failed to parse /register response!\nResponse: ${response2.body}`
          );
        }
      } else {
        console.error(
          `User [${this.username}] /register failed with status code ${response2.status}\nResponse: ${response2.body}`
        );
      }
    } else {
      console.error(
        `User [${this.username}] /register failed with status code ${registerResponse.status}\nResponse: ${registerResponse.body}`
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
        "Login Status is 200": (r) => r.status === 200,
      });

      const responseJson = response.json();
      this.access_token = responseJson.access_token;
      this.user_id = responseJson.user_id;
      this.device_id = responseJson.device_id;
      this.matrix_domain = this.user_id.split(":").pop();

      // Refresh tokens stored in the csv file
      updateTokens({
        data: {
          username: user.username,
          user_id: user.user_id,
          access_token: user.access_token,
          sync_token: "",
        },
      });

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
      console.error(
        `User [${this.username}] Can't set displayname without a user id`
      );
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
      displayname: displayname,
    };

    const response = this.matrix_api_call("PUT", url, body, label);

    // const response = http.put(url, JSON.stringify(body), { headers: { 'Content-Type': 'application/json' }, tags: { name: 'setDisplayName' } });

    check(response, {
      "Set Display Name Status is 200": (r) => r.status === 200,
    });

    if ("error" in response.json()) {
      console.error(`User [${user.username}] failed to set displayname`);
    }
  }

  matrix_api_call(method, url, body = null, name_tag = null) {
    if (this.access_token) {
      console.warn(`API call to ${url} failed -- No access token`);
      return null;
    }

    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
      Authorization: `Bearer ${this.access_token}`,
    };

    return http.request(method, url, {
      headers: headers,
      json: body,
      tags: { name: name_tag },
    });
  }
  async set_avatar_image(filename) {
    const blobUtil = require("blob-util");
    if (this.user_id === null) {
      console.error(
        `User [${this.username}] Can't set avatar image without a user id`
      );
      return;
    }

    // Guess the mimetype of the file
    const extension = filename.substring(filename.lastIndexOf(".") + 1);
    const mime_type = blobUtil.getMimetype(`.${extension}`);
    if (!mime_type) {
      console.error(
        `User [${this.username}] Failed to guess the mime type for the file`
      );
      return;
    }

    // Read the contents of the file
    const data = await fs.readFileSync(filename);

    // Upload the file to Matrix
    const mxc_url = await upload_matrix_media(data, mime_type);
    if (mxc_url === null) {
      console.error(`User [${this.username}] Failed to set avatar image`);
      return;
    }
    const url = `/_matrix/client/${this.matrix_version}/profile/${this.user_id}/avatar_url`;
    const body = JSON.stringify({
      avatar_url: mxc_url,
    });
    const label = `/_matrix/client/${this.matrix_version}/profile/_/avatar_url`;

    const response = await matrix_api_call("POST", url, body, label);
    return response;
  }

  async createRoom(alias, roomName, userIds = []) {
    const url = `/_matrix/client/${this.matrix_version}/createRoom`;
    const requestBody = JSON.stringify({
      preset: "private_chat",
      name: roomName,
      invite: userIds,
    });

    if (alias !== null) {
      requestBody.room_alias_name = alias;
    }

    try {
      const response = await matrix_api_call("POST", url, requestBody);
      const room_id = response.json().room_id;
      if (room_id === null) {
        console.error(
          `User [${this.username}] Failed to create room for [${roomName}]`
        );
        console.error(`${response.json().errcode}: ${response.json().error}`);
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
  async upload_matrix_media(data, content_type) {
    const url = `/_matrix/media/${this.matrix_version}/upload`;
    const headers = {
      "Content-Type": content_type,
      Accept: "application/json",
      Authorization: `Bearer ${this.access_token}`,
    };

    try {
      const response = http.post(url, JSON.stringify(data), headers);

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
  download_matrix_media(mxc) {
    // Convert the MXC URL to a "real" URL
    const toks = mxc.split("/");
    if (toks.length <= 2) {
      console.error(`Couldn't parse MXC URL [${mxc}]`);
    }
    const mediaId = toks[toks.length - 1];
    const serverName = toks[toks.length - 2];
    const realUrl = `/_matrix/media/${this.matrix_version}/download/${serverName}/${mediaId}`;

    // Check in your fake "cache" - Did you download this one already?
    const cached = this.media_cache[mxc] || false;

    if (!cached) {
      // Hit the Matrix /media API to download it
      const label = `/_matrix/media/${this.matrix_version}/download`;
      try {
        const response = matrix_api_call("GET", realUrl, null, label);
        // Mark it as cached so you don't download it again
        this.media_cache[mxc] = true;
      } catch (error) {
        console.error(`Error downloading media: ${error}`);
      }
    }
  }

  get_user_avatar_url(user_id) {
    const url = `/_matrix/client/${this.matrix_version}/profile/${user_id}/avatar_url`;
    const label = `/_matrix/client/${this.matrix_version}/profile/_/avatar_url`;

    try {
      const response = matrix_api_call("GET", url, null, label);
      const avatar_url = response.json().avatar_url || null;
      this.user_avatar_urls[user_id] = avatar_url;
    } catch (error) {
      console.error(`Error fetching user's avatar URL: ${error}`);
    }
  }

  get_user_displayname(user_id) {
    const url = `/_matrix/client/${this.matrix_version}/profile/${user_id}/displayname`;
    const label = `/_matrix/client/${this.matrix_version}/profile/_/displayname`;

    try {
      const response = matrix_api_call("GET", url, null, label);
      const displayname = response.displayname || null;
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
    const url = `/_matrix/client/${this.matrix_version}/rooms/${roomId}/join`;
    const label = `/_matrix/client/${this.matrix_version}/rooms/_/join`;

    try {
      const response = matrix_api_call("POST", url, null, label);

      if (!response) {
        console.error(
          `User [${this.username}] Failed to join room ${roomId} - timeout`
        );
        return null;
      }

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
    const url = `/_matrix/client/${this.matrix_version}/rooms/${roomId}/typing/${this.user_id}`;
    const body = JSON.stringify({
      timeout: 10 * 1000,
      typing: isTyping,
    });
    const label = `/_matrix/client/${this.matrix_version}/rooms/_/typing/_`;

    try {
      matrixApiCall("PUT", url, body, label);
    } catch (error) {
      console.error(`Error setting typing status: ${error}`);
    }
  }
  sendReadReceipt(roomId, eventId) {
    const url = `/_matrix/client/${this.matrix_version}/rooms/${roomId}/receipt/m.read/${eventId}`;
    const body = JSON.stringify({ thread_id: "main" });
    const label = `/_matrix/client/${this.matrix_version}/rooms/_/receipt/m.read/_`;

    try {
      matrix_api_call("POST", url, body, label);
    } catch (error) {
      console.error(`Error sending read receipt: ${error}`);
    }
  }
  sync_forever() {}
}
export default function () {
  let matrixuser_1 = new MatrixUser(
    (username = "hungtran"),
    (password = "123456789")
  );
  matrixuser_1.register();
  matrixuser_1.login();
  matrixuser_1.set_displayname("helloworld");
  matrixuser_1.set_avatar_image("avatar.png");
}
