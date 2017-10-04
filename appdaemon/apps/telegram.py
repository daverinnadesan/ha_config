import appdaemon.appapi as appapi 
import uuid
import enum
import json
ALARM_KEYBOARD = {
    'armStay'          :"Arm Stay".format(u'\U0001f3E1',u'\U0001f512'),
    'armAwayDelay' 	   :"Arm Away Delay".format(u'\U000023f3'),
		'armAway'          :"Arm Away".format(u'\U0001f510'),
    'sensorOverview'   :"Sensor Overview".format(u'\U0001f440'),
    'sensorBypass'     :"Zone Bypass".format(u'\U0001f515'),
    'backToMenu'       :"{} Menu".format(u'\U0001f3e0'),
    'panic'       	   :"{} Panic".format(u'\U0001f4e2'),
    'cameras'    		   :"{}".format(u'\U0001f4f9'),
    'disarm'           :"Disarm".format(u'\U0001f513'),
		'forceArm' 				 :"Force Arm",
		'alarmFunctions'	 :"Alarm Functions",
		'rooms'						 :"Rooms",
		'lights'					 :"Lights",
		'switches'				 :"Switches",
		'scenes'					 :"Scenes",
		'cameras'					 :"Cameras"}
ALARM_KEYBOARD_REVERSED = {v: k for k, v in ALARM_KEYBOARD.items()}
KEYBOARD_STRUCTURE = {
	'disarmed' : ['armStay',
							['armAway','armAwayDelay'],
							'sensorBypass',
							'sensorOverview',
							['backToMenu','panic','cameras']],
	'armed_home' : ['disarm',
							'sensorBypass',
							'sensorOverview',
							['backToMenu','panic','cameras']],
	'armed_away' : ['disarm',
							'sensorBypass',
							'sensorOverview',
							['backToMenu','panic','cameras']],
	'pending' : ['disarm',
							'forceArm',
							['backToMenu','panic']],
	'warning' : ['disarm',
							'forceArm',
							'sensorOverview',
							['backToMenu','panic','cameras']],
	'triggered' : ['disarm',
							'sensorOverview',
							['backToMenu','cameras']]}

TEXT_TO_SERVICE = {
	'armStay':'alarm_arm_home',
	'armAwayDelay':'alarm_arm_away',
	'armAway':'alarm_arm_instant',
	'disarm':'alarm_disarm',
	'forceArm':'alarm_arm_force',
	'panic':'alarm_trigger'
}
class TelegramBotEventListener(appapi.AppDaemon):
	"""Event Listener for Telegram bot events"""
	def initialize(self):
		self.log("Listening for telegram texts...")
		self.listen_event(self.receive_telegram_text, 'telegram_text')
		self.handle = None
		self.handleIncomingCode = None

	def getAccessGroup(self,userID, groupItems):
		accessgroup = None
		for group in groupItems:
			for chat_id in group[1]["chatids"]:
				if userID == chat_id:
					accessgroup = group[1]
					accessgroup['groupname'] = group[0]
					return accessgroup
		return accessgroup
		
	def pretty(self,d, indent=0):
		x = ''
		self.log("{} - {}".format(d,type(d)))
		for key, value in d.items():
				x+=('\t' * indent + str(key))
				if isinstance(value, dict):
						self.pretty(value, indent+1)
				else:
						x+=('\t' * (indent+1) + str(value))
		return x
	def receive_telegram_text(self, event_id, payload_event, *args):
		assert event_id == 'telegram_text'
		self.log("{---+")
		self.log(str(payload_event))
		accessgroup = self.getAccessGroup(str(payload_event["user_id"]),self.args["groups"].items())
		#self.log("ACCESS GROUP - <{}>".format(accessgroup))
		self.log("{} ---> {}".format(payload_event["from_first"],payload_event["text"]))
		if(accessgroup==None):
			self.errorMessage(payload_event,"User ID was not found\nPlease contact administrator")
			self.log("ERROR - user_id <{}> not found".format(payload_event["user_id"]))
		else:
			simpleFunction = ALARM_KEYBOARD_TO_METHOD.get(ALARM_KEYBOARD_REVERSED.get(payload_event['text']))
			if simpleFunction is not None:
					simpleFunction(self,payload_event,accessgroup)
			else:
					text = payload_event['text'].lower()
					replace_text = "{} back to ".format(u'\U0001f448')
					refined_text = text.replace(replace_text,"")
					self.log("{} ({}) ---> *{}*".format(text,replace_text,refined_text))
					text = payload_event['text'] = refined_text
					if text.startswith("turn off") or text.startswith("turn on"):
							self.turn_on_off(payload_event, accessgroup)
					elif text.startswith("bypass") or text.startswith("unbypass"):
							self.bypassZone(payload_event, accessgroup)
					elif self.isRoom(payload_event, accessgroup):
							self.roomControl(payload_event, accessgroup)
					elif self.endsWithEntity(payload_event, accessgroup):
							self.roomEntityControl(payload_event, accessgroup)
					elif text.startswith("bypass") or text.startswith("unbypass"):
							self.bypassZone(payload_event, accessgroup)
					else:
							self.printMenu(payload_event,accessgroup)

	def alarmFunction(self, payload_event, accessgroup):
		alarm_command = ALARM_KEYBOARD_REVERSED.get(payload_event['text'])
		alarm_service = TEXT_TO_SERVICE[alarm_command]
		chatid = str(payload_event['chat_id'])
		self.log("Calling Alarm Service {} from {}".format(alarm_service,chatid))
		service_result = self.call_service("alarm_control_panel/{}".format(alarm_service),entity_id = "alarm_control_panel.house", code = {'chat_id':chatid,'name':payload_event['from_first']})
		true_service_result = self.getTrueResult(service_result,"alarm_control_panel.house")
		#self.log("Service Result - {}".format(true_service_result))
		if true_service_result['state'] == 'pending':
			message = "Pending due to {}".format(true_service_result.get('attributes')['trippedsensors'])
			self.handle = self.listen_state(self.armDelayCallback, entity_id = 'alarm_control_panel.house',old = 'pending', chat_id = payload_event['chat_id'], accessgroup = accessgroup)	
		else:
			message = "Alarm *{}*".format(str(true_service_result['message']).upper())
		keyboard = self.getKeyboard(true_service_result['state'], accessgroup)
		self.call_service("telegram_bot/send_message",
			target = payload_event['chat_id'],
			message = message,
			keyboard = keyboard)

	def armDelayCallback(self, entity, attribute, old, new, kwargs):
		self.log("CALLBACK DELAY - {} - {} - {}".format(old,new,kwargs))
		if new != 'disarmed':
			keyboard = self.getKeyboard(new, kwargs['accessgroup'])
			self.call_service("telegram_bot/send_message",
				target = kwargs['chat_id'],
				message = "Alarm *{}*".format(new.upper()),
				keyboard = keyboard)
		self.cancel_listen_event(self.handle)
    	
	def getTrueResult(self, data, entity_id):
		#self.log("DATA - {}".format(data))
		for item in data:
			#self.log("ITEM - {}".format(item))
			if item.get('entity_id') == entity_id:
				if self.handle is not None:
					self.cancel_listen_event(self.handle)
				item['message'] = item['state']
				return item
		return {"state":self.get_state(entity_id), "message":"Aready {}".format(self.get_state(entity_id))}

	
	def sensorStatus(self, payload_event, accessgroup):
		self.log("Sensor Status")
		alarm_sensor_states = self.get_state("alarm_control_panel.house","all")
		all_sensor_states = self.get_state('binary_sensor')
		#self.log(alarm_sensor_states['attributes']['allsensors'])
		message = ''
		for eid in alarm_sensor_states['attributes']['allsensors']:
  			message+= "[{}] - {}\n".format(str(all_sensor_states[eid]['state']).upper(),all_sensor_states[eid]['attributes']['friendly_name'])
		self.log(message)
		self.call_service("telegram_bot/send_message",
			target = payload_event['chat_id'],
			message = message)

	def bypassZone(self, payload_event, accessgroup):
		splitText = payload_event['text'].split()
		self.log("BYPASS ZONE")
		all_group_states = self.get_state('group')
		friendly_name_text = "{} sensors".format(' '.join(splitText[1:]))
		entity_id = None
		for group in all_group_states.items():
				if type(group[1]) == dict:
					friendly_name_test = group[1]['attributes']['friendly_name'].lower()
					#self.log("<{}> - <{}>".format(friendly_name_text, friendly_name_test))
					if friendly_name_text == friendly_name_test:
						entity_id = group[0]
						break
		if entity_id:
  			result = self.call_service("alarm_control_panel/alarm_arm_{}_zone".format(splitText[0]),zone = entity_id)
		self.run_in(self.bypass(payload_event,accessgroup), 100)

	def bypass(self, payload_event, accessgroup):
		self.log("Bypass")
		alarm_state = self.get_state("alarm_control_panel.house","all")
		alarm_zones = alarm_state['attributes']['zones']

		bypassedSensors = alarm_state['attributes']['bypassedsensors']
		all_group_states = self.get_state('group')

		keyboard = []
		message = ''
		for zone_id in alarm_zones:
			zone_friendly_name = all_group_states[zone_id]['attributes']['friendly_name'].replace(" Sensors","")
			if set(all_group_states[zone_id]['attributes']['entity_id']) <= set(bypassedSensors):
					keyboard.append("Unbypass {0},{0} Sensors".format(zone_friendly_name))
					message+="{} {}\n".format(u'\U0000274C',zone_friendly_name)
			else:
					keyboard.append("Bypass {0},{0} Sensors".format(zone_friendly_name))
					message+="{} {}\n".format(u'\U00002705',zone_friendly_name)
		
		keyboard.append("{} Menu,{} Alarm Functions".format(u'\U0001f3e0',u'\U0001f448'))
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = message,
					disable_notification = True,
					keyboard = keyboard)
		
		
		#self.log(alarm_state)

	def panic(self, payload_event, accessgroup):
		self.log("Panic")
		result = self.call_service("alarm_control_panel/alarm_trigger",entity_id = "alarm_control_panel.house",code = {'chat_id':payload_event['chat_id'],'name':payload_event['from_first']})
		result = self.getTrueResult(result,"alarm_control_panel.house")
		self.log("True Result - {}".format(result))		
		keyboard = self.getKeyboard("triggered", accessgroup)
		self.call_service("telegram_bot/send_message",
			target = payload_event['chat_id'],
			message = "{} Alarm *{}*".format(u'\U000026d4',str(result['state']).upper()),
			keyboard = keyboard)

	def alarm_functions(self,payload_event, accessgroup):
		self.log("Serving Alarm Function Menu")
		alarm_state = self.get_state("alarm_control_panel.house","all")
		status = "Current Alarm Status - *{}*".format(str(alarm_state['state']).upper())
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = status,
					disable_notification = True,
					keyboard = self.getKeyboard(alarm_state['state'],accessgroup,payload_event))
		self.log(status)
		self.log("+---}")
	def roomEntityControl(self,payload_event, accessgroup):
		entity = payload_event["text"].split()[-1]
		room_text = payload_event["text"][:-(len(entity)+1)]
		room_object = None
		for room in accessgroup["rooms"]:
			friendly_name_temp = str(self.get_state(room,"friendly_name")).lower()
			if friendly_name_temp==room_text:
				room_object = room
		
		self.log("{} - {}".format(entity,room_text))
		keyboard = []
		group_entities = self.get_state(room_object,"attributes")["entity_id"]
		for group_entity in group_entities:
			if group_entity in accessgroup[entity]:
				friendly_name_temp = str(self.get_state(group_entity,"friendly_name"))
				keyboard.append("Turn on {0},Turn off {0}".format(friendly_name_temp))
		keyboard.append("Turn on all {0} {1}".format(room_text,entity))
		keyboard.append("Turn off all {0} {1}".format(room_text,entity))
		keyboard.append("{} Back to {},{} Back to Menu".format(u'\U0001f448',room_text,u'\U0001f3e0'))
			
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = "Which {} in the {} do you want to control?".format(entity,room_text),
					disable_notification = True,
					keyboard = keyboard)
		self.log("+---}")
	def endsWithEntity(self, payload_event, accessgroup):
		functions = ["lights","switches","scenes"]
		for function in functions:
			if payload_event["text"].endswith(function):
				room_text = payload_event["text"][:-(len(function)+1)]
				for room in accessgroup["rooms"]:
					friendly_name_temp = str(self.get_state(room,"friendly_name")).lower()
					if friendly_name_temp==room_text:
						return True
		return False
	def roomControl(self, payload_event, accessgroup):
		self.log("Serving Room Control Menu")
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = "Which do you want to control?",
					disable_notification = True,
					keyboard = self.getKeyboard("room_control",accessgroup,payload_event))
		self.log("+---}")
	def isRoom(self, payload_event, accessgroup):
		for room in accessgroup["rooms"]:
			friendly_name_temp = str(self.get_state(room,"friendly_name")).lower()
			self.log("*{}* =? *{}*".format(payload_event["text"],friendly_name_temp))
			if payload_event["text"]==friendly_name_temp:
				return True
		return False
	def turn_on_off(self, payload_event,accessgroup, *args):
		isOn = False
		isAll = False
		text = (payload_event['text']).replace(" the "," ").lower()
		friendly_name = text[8:].lstrip().lower()
		if text.startswith("turn on"): isOn = True
		self.log("Checking if entity is a light...")
		entity_labels = ["lights","switches"]
		self.log("Entity - {}".format(friendly_name))
		if friendly_name.startswith("all "):
			payload_event['text'] = friendly_name.replace("all ","")
			if(payload_event['text'] in accessgroup):
				self.log("IS A ENTITY!!!")
				entities = []
				for entity in accessgroup[payload_event['text']]:
					entities.append(entity)
				self.entity_turn_on_off(entities,entity,isOn,payload_event)
			elif(self.endsWithEntity(payload_event,accessgroup)):
				self.log("ENDS WITH ROOM ENTITY")
				entity = payload_event["text"].split()[-1]
				room_text = payload_event["text"][:-(len(entity)+1)]
				room_object = None
				for room in accessgroup["rooms"]:
					friendly_name_temp = str(self.get_state(room,"friendly_name")).lower()
					if friendly_name_temp==room_text:
						room_object = room
				group_entities = self.get_state(room_object,"attributes")["entity_id"]
				entities = []
				for group_entity in group_entities:
					if group_entity in accessgroup[entity]:
						entities.append(group_entity)
				self.entity_turn_on_off(entities,entity,isOn,payload_event)
			return
		self.log("Entity - {}".format(friendly_name))
		for entity_label in entity_labels:
			for entity in accessgroup[entity_label]:
				friendly_name_temp = str(self.get_state(entity,"friendly_name")).lower()
				if friendly_name==friendly_name_temp:
					self.log("Entity is a {}".format(entity_label))
					self.entity_turn_on_off(entity,friendly_name,isOn,payload_event)
					return
		self.log("Invalid Turn on/off request")
		self.errorMessage(payload_event, "Invalid Request")
				
	def entity_turn_on_off(self, entity_id,friendly_name, isOn, payload_event):
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = "Done {}".format(u'\U0001f44c'),
					disable_notification = False)
		if isOn:
			self.call_service("homeassistant/turn_on", entity_id = entity_id)
			self.log("Turning on {}".format(entity_id))
		else:
			self.call_service("homeassistant/turn_off", entity_id = entity_id)
			self.log("Turning off {}".format(entity_id))
		self.log("+---}")
	def getKeyboard(self,keyboard_type,accessgroup,payload_event = None):
		keyboard = []
		if keyboard_type=="menu":
			keyboard = accessgroup["menu"]
		elif keyboard_type=="switches" or keyboard_type=="lights" or keyboard_type=="other":
			for entity in accessgroup[keyboard_type]:
				friendly_name_temp = str(self.get_state(entity,"friendly_name"))
				keyboard.append("Turn on {0},Turn off {0}".format(friendly_name_temp))
			keyboard.append("Turn on all {0}".format(keyboard_type))
			keyboard.append("Turn off all {0}".format(keyboard_type))
			keyboard.append("{} Back to Menu".format(u'\U0001f3e0'))
		elif keyboard_type=="scenes":
			for entity in accessgroup["scenes"]:
				friendly_name_temp = str(self.get_state(entity,"entity_id"))
				keyboard.append("Turn on {}".format(friendly_name_temp))
			keyboard.append("{} Back to Menu".format(u'\U0001f3e0'))
		elif keyboard_type=="rooms":
			for entity in accessgroup["rooms"]:
				friendly_name_temp = str(self.get_state(entity,"friendly_name"))
				keyboard.append(friendly_name_temp)
			keyboard.append("{} Back to Menu".format(u'\U0001f3e0'))
		elif keyboard_type =="room_control":
			functions = ["lights","switches","scenes"]
			for entry in functions:
				keyboard.append("{} {}".format(payload_event["text"],entry))
			keyboard.append("{} Back to Rooms,{} Back to Menu".format(u'\U0001f448',u'\U0001f3e0'))
		elif keyboard_type in KEYBOARD_STRUCTURE.keys():
			keyboard = self.getRefinedKeyboard(KEYBOARD_STRUCTURE[keyboard_type],accessgroup['alarm']['functions'])						
		return keyboard

	def getRefinedKeyboard(self, keyboard, alarmAccessGroup):
		refinedKeyboard = []
		for item in keyboard:
			if(type(item) == str):
				if item not in alarmAccessGroup:
					refinedKeyboard.append(ALARM_KEYBOARD[item])
			else:
				line = ALARM_KEYBOARD[item[0]]
				for string in item[1:]:
					if string not in alarmAccessGroup:
						line += ",{}".format(ALARM_KEYBOARD[string])
				refinedKeyboard.append(line)
		return refinedKeyboard
	def control_lights(self,payload_event, accessgroup):
		self.log("Serving Light Menu")
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = "Which lights do you want to control? {}".format(u'\U0001f4a1'),
					disable_notification = True,
					keyboard = self.getKeyboard("lights",accessgroup,payload_event))
		self.log("+---}")
	def control_switches(self,payload_event, accessgroup):
		self.log("Serving Switch Menu")
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = "Which switches do you want to control?",
					disable_notification = True,
					keyboard = self.getKeyboard("switches",accessgroup,payload_event))
		self.log("+---}")
	def control_scenes(self, payload_event, accessgroup):
		self.log("Serving Scene Menu")
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = "Which scenes do you want to control?",
					disable_notification = True,
					keyboard = self.getKeyboard("scenes",accessgroup,payload_event))
		self.log("+---}")
	def printMenu(self,payload_event, accessgroup):
		self.log("Serving Main Menu")
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					title = "Hi {0} {1}".format(payload_event['from_first'],u'\U0001f44b'),
					message = "How can I help you?",
					disable_notification = True,
					keyboard = self.getKeyboard("menu",accessgroup,payload_event))
		self.log("+---}")
	def errorMessage(self,payload_event, error_text):
		self.log("Serving Error Message")
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					title = "Error",
					message = error_text,
					disable_notification = True)
		self.log("+---}")
	def rooms(self, payload_event, accessgroup):
		self.log("Serving Room Menu")
		self.call_service("telegram_bot/send_message",
					target = payload_event['chat_id'],
					message = "Which room do you want to control?",
					disable_notification = True,
					keyboard = self.getKeyboard("rooms",accessgroup,payload_event))
		self.log("+---}")
		
ALARM_KEYBOARD_TO_METHOD = {
	'armStay'          :TelegramBotEventListener.alarmFunction,
	'armAwayDelay' 	   :TelegramBotEventListener.alarmFunction,
	'sensorOverview'   :TelegramBotEventListener.sensorStatus,
	'sensorBypass'     :TelegramBotEventListener.bypass,
	'backToMenu'       :TelegramBotEventListener.printMenu,
	'panic'       	   :TelegramBotEventListener.alarmFunction,
	'cameras'    		   :None,
	'disarm'           :TelegramBotEventListener.alarmFunction,
	'armAway'          :TelegramBotEventListener.alarmFunction,
	'forceArm' 				 :TelegramBotEventListener.alarmFunction,
	'alarmFunctions'	 :TelegramBotEventListener.alarm_functions,
	'rooms'						 :TelegramBotEventListener.rooms,
	'lights'					 :TelegramBotEventListener.control_lights,
	'switches'				 :TelegramBotEventListener.control_switches,
	'scenes'					 :TelegramBotEventListener.control_scenes,
	}