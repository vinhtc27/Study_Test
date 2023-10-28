#!/bin/env python3

import os
import sys
import glob

import csv
import json
import random

PARETO_ALPHA = 1.161 # 80/20 rule.  See also: https://en.wikipedia.org/wiki/Pareto_distribution#Relation_to_the_%22Pareto_principle%22

# First load the roster of users from users.csv
users = []
with open("users.csv", "r") as csvfile:
  reader = csv.DictReader(csvfile)
  for row in reader:
    username = row["username"]
    print("Found user [%s]" % username)
    users.append(username)
num_users = len(users)

#num_rooms = int(len(users) / 2)
max_num_rooms = num_users
# Then generate a bunch of rooms with their sizes from a power law distribution
room_sizes = []
room_sizes_sum = 0.0
for i in range(max_num_rooms):
  s = round(random.paretovariate(PARETO_ALPHA))
  if s > num_users:
    s = num_users
  if s < 2:
    #s = 2
    continue
  print("s = %d" % s)
  room_sizes.append(s)
  room_sizes_sum += s
num_rooms = len(room_sizes)
avg = room_sizes_sum / num_rooms

print("###################################")
print("%d Total rooms" % num_rooms)
print("Max = %f" % max(room_sizes))
print("Min = %f" % min(room_sizes))
print("Avg = %f" % avg)
print("###################################")

# Now assign the users (randomly) to the slots in the rooms
room_members = {}
for i in range(num_rooms):
  room_name = "Room %d" % i
  num_members = room_sizes[i]
  room_members[room_name] = random.sample(users, num_members)

# Save the room assignments to a file
with open("rooms.json", "w") as jsonfile:
  jsonfile.write(json.dumps(room_members))

# Analyze the set of room assignments from the users' point of view
assignments = {}
for room, members in room_members.items():
  for member in members:
    if member in assignments:
      assignments[member] += 1
    else:
      assignments[member] = 1
roomless = []
in_all_rooms = []
centurions = []
for user in users:
  user_num_rooms = assignments.get(user, 0)
  if user_num_rooms < 1:
    roomless.append(user)
  if user_num_rooms == num_rooms:
    in_all_rooms.append(user)
  if user_num_rooms > 99:
    centurions.append(user)

print("%d users in zero rooms" % len(roomless))
print("%d users in all rooms" % len(in_all_rooms))
print("%d users in > 100 rooms" % len(centurions))

