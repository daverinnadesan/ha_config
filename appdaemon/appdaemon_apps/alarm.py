import appdaemon.appapi as appapi
import random
import json


class AlarmReaction(appapi.AppDaemon):
    def initialize(self):
        self.log("Listening for Alarm Triggers....")
        #self.listen_state(self.alarmLights, self.args['alarm_lights'])
        #self.listen_state(self.alarmSounds, self.args['alarm_sounds'])
        self.listen_event(self.alarmListener, 'state_changed', entity_id = 'alarm_control_panel.house')
        self.telegram = self.get_app("Telegram")

    def alarmListener(self, event_name, data, kwargs):
        self.log("<<...")
        self.trigger(data,kwargs)
        self.log("...>>")

    def trigger(self, data, kwargs):
        #self.log("ARMED HOME - <{}> - <{}>".format(data,kwargs))
        new_state = data['new_state']['state']
        # activateAction(new_state)
        self.log("Event Trigger for  :{}".format(str(new_state).upper()))
        triggered_by = self.getTriggeredBy(data)
        self.log("Triggered by       :{}".format(triggered_by['name']))
        self.log("Notifying")
        self.telegram_notify(new_state, triggered_by)
        self.log("...>>")

    def getTriggeredBy(self, data):
        triggered_by = data['new_state']['attributes'].get('triggeredBy',None)
        self.log("TRIGGEDER YBY - {}".format(triggered_by))
        if triggered_by in [list(),None,'','None']:
            if data['new_state']['state'] in ['triggered','warning']:
                triggered_by = {'name': self.friendly_name(data['new_state']['attributes']['changed_by'])}
            else:
                triggered_by = {'name':'Web Console'}
        else:
            triggered_by = json.loads(triggered_by.replace("\'","\""))
        return triggered_by
        
    def telegram_notify(self,new_state,triggered_by):
        telegram_groups = self.config['Telegram']["groups"].items()
        count = 0
        for user_group in self.args['notify_{}'.format(new_state)]:
            for chat_id in self.config['Telegram']['groups'][user_group]['chatids']:
                if triggered_by.get('chat_id') != chat_id:
                    count += 1
                    self.log("[{}] {}".format(user_group,chat_id))
                    accessgroup = self.telegram.getAccessGroup(str(chat_id),telegram_groups)
                    keyboard = self.telegram.getKeyboard(new_state,accessgroup)
                    self.call_service("telegram_bot/send_message",
                        target = chat_id,
                        message = self.getMessage(new_state,triggered_by['name']),
                        keyboard = keyboard)
        self.log("{} user(s) successfully notified".format(count))

    def getMessage(self,new_state,triggered_by_name):
        messages = {"armed_home":"Alarm *ARMED (Stay)* by {}".format(triggered_by_name),
                    "armed_away":"Alarm *ARMED (Away)* by {}".format(triggered_by_name) ,
                    "pending":"Alarm *PENDING ARM* by {}".format(triggered_by_name),
                    "warning":"{0} *Warning* by {1}".format(u'\U000026a0',triggered_by_name),
                    "disarmed":"Alarm *DISARMED* by {}".format(triggered_by_name),
                    "triggered":"{0} Alarm *TRIGGERED* by {1}".format(u'\U000026d4',triggered_by_name)}
        return messages.get(new_state)

    def alarmLights(self, entity, attribute, old, new, kwargs):
        if new == 'on':
            self.log("LIGHT ALARM ACTIVATED - <{}> - <{}>".format(entity,new))
            self.turn_on(self.args['lights'],True)
        else:
            self.log("LIGHT ALARM DISABLED - <{}> - <{}>".format(entity,new))
            self.turn_on(self.args['lights'],False)
        self.log(self.args['lights'])

    def alarmSounds(self, entity, attribute, old, new, kwargs):
        if new == 'on':
            self.log("SOUND ALARM ACTIVATED - <{}> - <{}>".format(entity,new))
            self.audioLoop(self.args['xiaomis'],True)
        else:
            self.log("SOUND ALARM DISABLED - <{}> - <{}>".format(entity,new))
            self.audioLoop(self.args['xiaomis'],False)
    
    def audioLoop(self, xiaomis, repeat):
        for xiaomi in xiaomis:
            self.log("XIAOMI!!")
            self.call_service("xiaomi/play_ringtone", gw_mac = xiaomi.get('gw_mac'), ringtone_id = xiaomi.get('ringtone_id'), ringtone_vol = xiaomi.get('ringtone_vol'))
        if repeat==True:
            if self.get_state('input_boolean.alarm_sounds') == 'on':
                pass#self.run_in(self.audioLoop(xiaomis,repeat),20)
        else:
            for xiaomi in xiaomis:
                self.log("XIAOMI STOP!!")
                self.call_service("xiaomi/stop_ringtone", gw_mac = xiaomi.get('gw_mac'))

    def turn_on(self, lights, repeat):
        strobeLights = []
        rgbwLights = []
        for light in self.args['lights']:  
            self.log("LIGGHT - <{}> - <{}>".format(light.get('entity_id'),light.get('effect')))
            if light.get('effect') is not None:
                rgbwLights.append(light['entity_id'])
                self.call_service("light/turn_on", entity_id = light.get('entity_id'), effect = light.get('effect'))
            else:
                strobeLights.append(light['entity_id'])
        self.call_service("homeassistant/turn_on", entity_id = strobeLights)
        if repeat == True:
            if self.get_state('input_boolean.alarm_lights') == 'on':
                self.turn_off(strobeLights)
        else:
            self.call_service("light/turn_on", entity_id = rgbwLights, effect = "Stop")

    def turn_off(self, lights):
        self.log("OFF - {}".format(lights))
        self.call_service("homeassistant/turn_off", entity_id = lights)
        self.turn_on(lights, True)
