#!/bin/env python3

import argparse
import random

import csv

parser = argparse.ArgumentParser(
    description="Generates a list of matrix users to store in a .csv file")
parser.add_argument("num_users", type=int, default=1000, nargs="?",
                    help="Number of users to generate")
parser.add_argument("-o", "--output", type=str, default="users.csv", nargs="?",
                    help="Output .csv file path")

args = parser.parse_args()

with open(args.output, "w", encoding="utf-8") as csvfile:
    fieldnames = ["username", "password"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for i in range(args.num_users):
        username = "user.%06d" % i
        # WARNING: This is not a safe way to generate real passwords!
        #          Do not do this in real life!
        #          Instead, use the Python `secrets` module.
        #          Here we just want a quick way to generate lots of
        #          passwords without eating up our system's entropy pool,
        #          and anyway these are accounts that we are going to
        #          throw away at the end of the test.
        password = "".join(random.choices("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", k=16))
        print(f"username = [{username}]\tpassword = [{password}]")

        # Access token will be populated when the user is registered
        writer.writerow({"username": username, "password": password})
