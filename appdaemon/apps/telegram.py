import appdaemon.appapi as appapi

class TelegramBotEventListener(appapi.AppDaemon):
	"""Event Listener for Telegram bot events"""

	def initialize(self):
		self.log("Listening for telegram texts...")
		self.listen_event(self.receive_telegram_text, 'telegram_text')

	def receive_telegram_text(self, event_id, payload_event, *args):
		assert event_id == 'telegram_text'
		self.log("{---+")
		self.log(str(payload_event))
		accessgroup = None
		for group in self.args["groups"].items():
			if(payload_event["user_id"] in group[1]["chatids"]):
				self.log("User is part of the \'{}\' group".format(group[0]))
				accessgroup = group[1]
		self.log("{} ---> {}".format(payload_event["from_first"],payload_event["text"]))
		if(accessgroup==None):
			self.errorMessage(payload_event,"User ID was not found\nPlease contact administrator")
			self.log("ERROR - user_id <{}> not found".format(payload_event["user_id"]))
		else:
			text = payload_event['text'].lower()
			replace_text = "{} back to ".format(u'\U0001f448')
			refined_text = text.replace(replace_text,"")
			self.log("{} ({}) ---> *{}*".format(text,replace_text,refined_text))
			text = payload_event['text'] = refined_text
			if text.startswith("turn off") or text.startswith("turn on"):
				self.turn_on_off(payload_event, accessgroup)
			elif text == "lights":
				self.control_lights(payload_event, accessgroup)
			elif text == "switches":
				self.control_switches(payload_event, accessgroup)
			elif text == "scenes":
				self.control_scenes(payload_event, accessgroup)
			elif text == "rooms":
				self.rooms(payload_event, accessgroup)
			elif text == "alarm functions":
				pass#self.alarm_functions(text)
			elif text == "cameras":
				pass#self.camera(text)
			elif self.isRoom(payload_event, accessgroup):
				self.roomControl(payload_event, accessgroup)
			elif self.endsWithEntity(payload_event, accessgroup):
				self.roomEntityControl(payload_event, accessgroup)
			else:
				self.printMenu(payload_event,accessgroup)

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
				friendly_name_temp = str(self.get_state(group_entity,"friendly_name")).lower()
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

	def getKeyboard(self,keyboard_type,accessgroup,payload_event):
		keyboard = []
		if keyboard_type=="menu":
			keyboard = accessgroup["menu"]
		elif keyboard_type=="switches" or keyboard_type=="lights" or keyboard_type=="other":
			for entity in accessgroup[keyboard_type]:
				friendly_name_temp = str(self.get_state(entity,"friendly_name")).lower()
				keyboard.append("Turn on {0},Turn off {0}".format(friendly_name_temp))
			keyboard.append("Turn on all {0}".format(keyboard_type))
			keyboard.append("Turn off all {0}".format(keyboard_type))
			keyboard.append("{} Back to Menu".format(u'\U0001f3e0'))
		elif keyboard_type=="scenes":
			for entity in accessgroup["scenes"]:
				friendly_name_temp = str(self.get_state(entity,"entity_id")).lower()
				keyboard.append("Turn on {}".format(friendly_name_temp))
			keyboard.append("{} Back to Menu".format(u'\U0001f3e0'))
		elif keyboard_type=="rooms":
			for entity in accessgroup["rooms"]:
				friendly_name_temp = str(self.get_state(entity,"friendly_name")).lower()
				keyboard.append(friendly_name_temp)
			keyboard.append("{} Back to Menu".format(u'\U0001f3e0'))
		elif keyboard_type =="room_control":
			functions = ["lights","switches","scenes"]
			for entry in functions:
				keyboard.append("{} {}".format(payload_event["text"],entry))
			keyboard.append("{} Back to Rooms,{} Back to Menu".format(u'\U0001f448',u'\U0001f3e0'))
		return keyboard

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


		

