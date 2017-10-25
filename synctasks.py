import json
import requests
import sys
import webbrowser

from configobj import ConfigObj
from datetime import datetime
from functools import reduce

from rtmapi import Rtm

HABITICA_API = 'https://habitica.com/api/v3/'
TASKS_URL = '{}tasks/user'.format(HABITICA_API)
TODOS_URL = '{}?type=todos'.format(TASKS_URL)
COMPLETED_TODOS_URL = '{}?type=completedTodos'.format(TASKS_URL)


if __name__ == '__main__':
    config = ConfigObj('rtmhabit.ini')
    rtm = config['rtm']
    habitica = config['habitica']
    to_sync = rtm['to_sync']

    cache = ConfigObj('.cache', create_empty=True)
    api = Rtm(rtm['api_key'], rtm['shared_secret'], 'delete', cache.get('token'))

    # authentication block, see http://www.rememberthemilk.com/services/api/authentication.rtm
    # check for valid token
    if not api.token_valid():
        # use desktop-type authentication
        url, frob = api.authenticate_desktop()
        # open webbrowser, wait until user authorized application
        webbrowser.open(url)
        input('Continue?')
        # get the token for the frob
        api.retrieve_token(frob)
        # store the new token, should be used to initialize the Rtm object next time
        cache['token'] = api.token
        cache.write()

    result = api.rtm.timelines.create()
    timeline = result.timeline.value

    # get all open habitica to-dos, see https://habitica.com/apidoc/#api-Task-GetUserTasks
    headers = {
        'x-api-user': habitica['user_id'],
        'x-api-key': habitica['api_token']
    }
    r = requests.get(TODOS_URL, headers=headers)
    r.raise_for_status()
    response = r.json()
    habitica_todos = response['data']
    aliases = [x['alias'] for x in habitica_todos if x.get('alias') is not None]

    # get all recently completed habitica to-dos, see https://habitica.com/apidoc/#api-Task-GetUserTasks
    r = requests.get(COMPLETED_TODOS_URL, headers=headers)
    r.raise_for_status()
    response = r.json()
    habitica_completed_todos = response['data']
    completed_aliases = [x['alias'] for x in habitica_completed_todos if x.get('alias') is not None]

    # get all open next actions, see http://www.rememberthemilk.com/services/api/methods/rtm.tasks.getList.rtm
    open_tasks_filter = '{} AND status:incomplete'.format(to_sync)
    closed_tasks_filter = '{} AND status:complete'.format(to_sync)

    last_sync = cache.get('last_sync')
    now = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    if last_sync is not None:
        open_tasks = api.rtm.tasks.getList(filter=open_tasks_filter, last_sync=last_sync)
        closed_tasks = api.rtm.tasks.getList(filter=closed_tasks_filter, last_sync=last_sync)
    else:
        open_tasks = api.rtm.tasks.getList(filter=open_tasks_filter)
        closed_tasks = api.rtm.tasks.getList(filter=closed_tasks_filter)

    cache['last_sync'] = now
    cache.write()

    new_tasks = []
    for tasklist in open_tasks.tasks:
        for taskseries in tasklist:
            if taskseries.task.id in completed_aliases:
                result = api.rtm.tasks.complete(timeline=timeline, list_id=tasklist.id, taskseries_id=taskseries.id, task_id=taskseries.task.id)
                print('› Checked off completed Habitica to-do "{}" on RTM'.format(taskseries.name))
            elif taskseries.task.id not in aliases:
                habit_task = {
                    "text": taskseries.name,
                    "type": "todo",
                    "alias": taskseries.task.id
                }
                if taskseries.task.due:
                    habit_task['date'] = taskseries.task.due
                new_tasks.append(habit_task)

    completed_tasks = []
    for tasklist in closed_tasks.tasks:
        for taskseries in tasklist:
            if taskseries.task.id in aliases:
                r = requests.post('{}tasks/{}/score/up'.format(HABITICA_API, taskseries.task.id), headers=headers)
                r.raise_for_status()
                print('› Checked off completed RTM task "{}" on Habitica'.format(taskseries.name))

    if len(new_tasks):
        r = requests.post(TASKS_URL, headers=headers, json=new_tasks)
        r.raise_for_status()
        print('› Imported tasks from RTM → Habitica')


    print('Habitica and RTM are up-to-date 🎉')
