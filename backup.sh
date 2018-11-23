#! /bin/bash


date
ps aux | grep -v grep | grep duply > /dev/null
RUNNING=$?

if [ $RUNNING -ne 0 ]; then
	echo "Backing up"
	duply heaters backup
	killall -r "*duply*"
	killall -r "*duplicity*"
else
	echo "Duply already running"
fi

