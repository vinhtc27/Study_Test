###########################################################
#
# matrixchatuser.py - The MatrixChatUser class
# -- Acts like a Matrix chat user
#
# Created: 2022-08-05
# Author: Charles V Wright <cvwright@futo.org>
# Copyright: 2022 FUTO Holdings Inc
# License: Apache License version 2.0
#
# The MatrixChatUser class extends MatrixUser to add some
# basic chatroom user behaviors.

# Upon login to the homeserver, this user spawns a second
# "background" Greenlet to act as the user's client's
# background sync task.  The "background" Greenlet sleeps and
# calls /sync in an infinite loop, and it uses the responses
# to /sync to populate the user's local understanding of the
# world state.
#
# Meanwhile, the user's main "foreground" Greenlet does the
# things that a Locust User normally does, sleeping and then
# picking a random @task to execute.  The available set of
# @tasks includes: accepting invites to join rooms, sending
# m.text messages, sending reactions, and paginating backward
# in a room.
#
###########################################################

import csv
import os
import sys
import glob
import random
import resource

import json
import logging

import gevent
from locust import task, between, TaskSet
from locust import events
from locust.runners import MasterRunner, WorkerRunner

from matrixuser import MatrixUser


# Preflight ###############################################

@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    # Increase resource limits to prevent OS running out of descriptors
    resource.setrlimit(resource.RLIMIT_NOFILE, (999999, 999999))

    # Multi-worker
    if isinstance(environment.runner, WorkerRunner):
        print(f"Registered 'load_users' handler on {environment.runner.client_id}")
        environment.runner.register_message("load_users", MatrixChatUser.load_users)
    # Single-worker
    elif not isinstance(environment.runner, WorkerRunner) and not isinstance(environment.runner, MasterRunner):
      # Open our list of users
      MatrixChatUser.worker_users = csv.DictReader(open("users.csv"))

# Load our images and thumbnails
images_folder = "images"
image_files = glob.glob(os.path.join(images_folder, "*.jpg"))
images_with_thumbnails = []
for image_filename in image_files:
  image_basename = os.path.basename(image_filename)
  thumbnail_filename = os.path.join(images_folder, "thumbnails", image_basename)
  if os.path.exists(thumbnail_filename):
    images_with_thumbnails.append(image_filename)

# Find our user avatar images
avatars = []
avatars_folder = "avatars"
avatar_files = glob.glob(os.path.join(avatars_folder, "*.png"))

# Pre-generate some messages for the users to send
lorem_ipsum_text = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
"""
lorem_ipsum_words = lorem_ipsum_text.split()

lorem_ipsum_messages = {}
for i in range(1, len(lorem_ipsum_words)+1):
  lorem_ipsum_messages[i] = " ".join(lorem_ipsum_words[:i])

###########################################################



class MatrixChatUser(MatrixUser):
  worker_id = None
  worker_users = []

  @staticmethod
  def load_users(environment, msg, **_kwargs):
      MatrixChatUser.worker_users = iter(msg.data)
      MatrixChatUser.worker_id = environment.runner.client_id
      logging.info("Worker [%s] Received %s users", environment.runner.client_id, len(msg.data))

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)



  def on_start(self):
    # Load the next user who needs to be logged-in
    try:
      user_dict = next(MatrixChatUser.worker_users)
    except StopIteration:
      gevent.sleep(999999)
      return

    # Change to force user login request and refresh tokens
    invalidate_access_tokens = False

    self.login_from_csv(user_dict)

    if invalidate_access_tokens:
      self.user_id = None
      self.access_token = None

    if not (self.user_id is None) and not (self.access_token is None):
      self.start_syncing()

    # First log in if not logged in already
    if self.username is None or self.password is None:
      logging.error("No username or password")
      self.environment.runner.quit()
    else:
      #logging.info("Logging in user [%s] with password [%s]" % (self.username, self.password))

      while self.user_id is None or self.access_token is None:
        # The login() method sets user_id, device_id, and access_token
        # And if we ask it to, it also starts our "backgound" sync task
        self.login(start_syncing = True, log_request = True)


  def on_stop(self):
    pass
    # Currently we don't want to invalidate access tokens stored in the csv file
    # self.logout()



  @task(23)
  def do_nothing(self):
    self.wait()



  @task(1)
  def send_text(self):
    room_id = self.get_random_roomid()
    if room_id is None:
      #logging.warning("User [%s] couldn't get a room for send_text" % self.username)
      #self.accept_invites()
      return
    #logging.info("User [%s] sending a message to room [%s]" % (self.username, room_id))

    # Send the typing notification like a real client would
    self.set_typing(room_id, True)
    # Sleep while we pretend the user is banging on the keyboard
    delay = random.expovariate(1.0 / 5.0)
    gevent.sleep(delay)

    message_len = round(random.lognormvariate(1.0, 1.0))
    message_len = min(message_len, len(lorem_ipsum_words))
    message_len = max(message_len, 1)
    message_text = lorem_ipsum_messages[message_len]

    event = {
      "type": "m.room.message",
      "content": {
        "msgtype": "m.text",
        "body": message_text,
      }
    }
    with self.send_matrix_event(room_id, event) as response:
      if "error" in response.js:
        logging.error("User [%s] failed to send m.text to room [%s]" % (self.username, room_id))
      #elif "event_id" in response.js:
      #  event_id = response.js["event_id"]
      #  #logging.info("User [%s] successfully sent event with id = [%s]" % (self.username, event_id))



  @task(4)
  def look_at_room(self):
    room_id = self.get_random_roomid()
    if room_id is None:
      #logging.warning("User [%s] couldn't get a roomid for look_at_room" % self.username)
      #self.accept_invites()
      return
    #logging.info("User [%s] looking at room [%s]" % (self.username, room_id))
    self.load_data_for_room(room_id)

    messages = self.recent_messages.get(room_id, [])
    if messages is None or len(messages) < 1:
      return

    last_msg = messages[-1]
    event_id = last_msg.get("event_id", None)
    if event_id is not None:
      self.send_read_receipt(room_id, event_id)



  # FIXME Combine look_at_room() and paginate_room() into a TaskSet,
  #       so the user can paginate and scroll the room for a longer
  #       period of time.
  #       In this model, we should load the displaynames and avatars
  #       and message thumbnails every time we paginate, just like a
  #       real client would do as the user scrolls the timeline.
  @task
  def paginate_room(self):
    room_id = self.get_random_roomid()
    token = self.earliest_sync_tokens.get(room_id, self.initial_sync_token)
    if room_id is None or token is None:
      return
    url = "/_matrix/client/%s/rooms/%s/messages?dir=b&from=%s" % (self.matrix_version, room_id, token)
    label = "/_matrix/client/%s/rooms/_/messages" % self.matrix_version
    with self._matrix_api_call("GET", url, name=label) as response:
      if not "chunk" in response.js:
        logging.warning("User [%s] GET /messages failed for room %s" % (self.username, room_id))
      if "end" in response.js:
        self.earliest_sync_tokens[room_id] = response.js["end"]

  # Disabling accept_invites now that the join setup script works correctly

  # @task(8)
  # def accept_invites(self):
  #   # Pick a random invited room and join it
  #   #logging.info("User [%s] has %d pending invites" % (self.username, len(self.invited_room_ids)))
  #   if len(self.invited_room_ids) > 0:
  #     room_id = random.choice(list(self.invited_room_ids))
  #     if room_id is None:
  #       return
  #     # Pretend that the user is looking at the invitation and deciding whether to accept
  #     delay = random.expovariate(1.0 / 5.0)
  #     gevent.sleep(delay)
  #     # Now accept the invite
  #     room_id = self.join_room(room_id)
  #     if room_id is None:
  #       # Hmm, somehow the join failed...
  #       # Maybe the server is just too swamped right now?  Maybe if we back off a bit, things will get better...
  #       return



  @task(1)
  def go_afk(self):
    logging.info("User [%s] going away from keyboard" % self.username)
    # Generate large(ish) random away time
    away_time = random.expovariate(1.0 / 600.0)  # Expected value = 10 minutes
    gevent.sleep(away_time)


  @task(1)
  def change_displayname(self):
    user_number = self.username.split(".")[-1]
    random_number = random.randint(1,1000)
    new_name = "User %s (random=%d)" % (user_number, random_number)
    self.set_displayname(displayname=new_name)


  @task(3)
  class ChatInARoom(TaskSet):

    def wait_time(self):
      expected_wait = 25.0
      rate = 1.0 / expected_wait
      return random.expovariate(rate)

    def on_start(self):
      #logging.info("User [%s] chatting in a room" % self.user.username)
      if len(self.user.joined_room_ids) == 0:
        self.interrupt()
      else:
        self.room_id = self.user.get_random_roomid()
        if self.room_id is None:
          self.accept_invites()
          self.interrupt()
        else:
          self.user.load_data_for_room(self.room_id)

    @task
    def send_text(self):

      # Send the typing notification like a real client would
      self.user.set_typing(self.room_id, True)
      # Sleep while we pretend the user is banging on the keyboard
      delay = random.expovariate(1.0 / 5.0)
      gevent.sleep(delay)

      message_len = round(random.lognormvariate(1.0, 1.0))
      message_len = min(message_len, len(lorem_ipsum_words))
      message_len = max(message_len, 1)
      message_text = lorem_ipsum_messages[message_len]

      event = {
        "type": "m.room.message",
        "content": {
          "msgtype": "m.text",
          "body": message_text,
        }
      }
      with self.user.send_matrix_event(self.room_id, event) as response:
        if not "event_id" in response.js:
          logging.warning("User [%s] Failed to send/chat in room %s" % (self.user.username, self.room_id))

    @task
    def send_image(self):
      # Choose an image to send/upload
      # Upload the thumbnail -- FIXME We need to have all of the thumbnails created and stored *before* we start the test.  Performance will be awful if we're trying to dynamically resample the images on-the-fly here in the load generator.
      # Upload the image data, get back an MXC URL
      # Craft the event JSON structure
      # Send the event
      pass


    @task
    def send_reaction(self):
      #logging.info("User [%s] sending reaction" % self.user.username)
      # Pick a recent message from the selected room,
      # and react to it
      messages = self.user.recent_messages.get(self.room_id, [])
      if messages is None or len(messages) < 1:
        return
      message = random.choice(messages)
      reaction = random.choice(["💩","👍","❤️", "👎", "🤯", "😱", "👏"])
      event = {
        "type": "m.reaction",
        "content": {
          "m.relates_to": {
            "rel_type": "m.annotation",
            "event_id": message["event_id"],
            "key": reaction,
          }
        }
      }
      with self.user.send_matrix_event(self.room_id, event) as _response:
        pass

    @task
    def stop(self):
      #logging.info("User [%s] stopping chat in room [%s]" % (self.user.username, self.room_id))
      self.interrupt()

    # Each time we create a new instance of this task, we want to have the user
    # generate a slightly different expected number of messages.
    # FIXME Hmmm this doesn't seem to work...
    tasks = {
      send_text: max(1, round(random.gauss(15,4))),
      send_image: random.choice([0,0,0,1,1,2]),
      send_reaction: random.choice([0,0,1,1,1,2,3]),
      stop: 1,
    }

