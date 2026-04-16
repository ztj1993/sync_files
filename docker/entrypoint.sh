#!/bin/sh

i=1
while true; do
    schedule=$(printenv "CRON_${i}_SCHEDULE")
    command=$(printenv "CRON_${i}_COMMAND")
    logfile=$(printenv "CRON_${i}_LOGFILE")

    if [ -z "$schedule" ] || [ -z "$command" ]; then
        break
    fi

    if [ -z "$logfile" ]; then
        logfile="/var/log/cron_${i}.log"
    fi

    echo "Job $i schedule: $schedule"
    echo "Job $i command:  $command"
    echo "Job $i logfile:  $logfile"

    echo "$schedule cd /app && $command >> $logfile 2>&1" >> /etc/crontabs/root

    i=$((i + 1))
done

exec "$@"
