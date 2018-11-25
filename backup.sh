#! /bin/bash


date
ps aux | grep -v grep | grep duply > /dev/null
RUNNING=$?

if [ $RUNNING -ne 0 ]; then
	echo "Backing up"
	timeout 60m "/usr/bin/duply heaters backup"
	killall -s SIGKILL -r "*duply*"
	killall -s SIGKILL -r "*duplicity*"
else
	echo "Duply already running"
fi

