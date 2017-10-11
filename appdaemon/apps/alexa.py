import appdaemon.appapi as appapi
import random

class Alexa(appapi.AppDaemon):
    def initialize(self):
        self.register_endpoint(self.api_call,"alexa")

    def api_call(self, data):
        self.log("HEREEE")
        intent = self.get_alexa_intent(data)
        if intent is not None:
            all_solts = self.get_alexa_slot_value(data)
            self.log(all_solts)
            self.log(data)
            return "200","Success"
        else:
            self.log("Alexa error encountered: {}".format(self.get_alexa_error(data)))
            return "", 201



 