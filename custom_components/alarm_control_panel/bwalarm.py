"""
  My take on the manual alarm control panel
"""
import asyncio
import datetime
import logging
import enum
import re
import voluptuous as vol
from operator import attrgetter

from homeassistant.const import (
    STATE_ALARM_ARMED_AWAY, STATE_ALARM_ARMED_HOME, STATE_ALARM_DISARMED,
    STATE_ALARM_PENDING, STATE_ALARM_TRIGGERED, CONF_PLATFORM, CONF_NAME,
    CONF_CODE, CONF_PENDING_TIME, CONF_TRIGGER_TIME, CONF_DISARM_AFTER_TRIGGER,
    EVENT_STATE_CHANGED, EVENT_TIME_CHANGED, STATE_ON)
from homeassistant.util.dt import utcnow as now
from homeassistant.helpers.event import async_track_point_in_time
import homeassistant.components.alarm_control_panel as alarm
import homeassistant.components.switch as switch
import homeassistant.components.input_boolean as input_boolean
import homeassistant.helpers.config_validation as cv

CONF_HEADSUP   = 'headsup'
CONF_IMMEDIATE = 'immediate'
CONF_DELAYED   = 'delayed'
CONF_NOTATHOME = 'notathome'
CONF_ALARM     = 'alarm'
CONF_WARNING   = 'warning'
CONF_ZONES     = 'zones'

DOMAIN = 'alarm_control_panel'

# Add a new state for the time after an delayed sensor and an actual alarm
STATE_ALARM_WARNING = 'warning'


class Events(enum.Enum):
    ImmediateTrip       = 1
    DelayedTrip         = 2
    ArmHome             = 3
    ArmHomeForce        = 4
    ArmAway             = 5
    ArmAwayForce        = 6
    ArmAwayDelay        = 7
    ArmAwayDelayForce   = 8
    Timeout             = 9
    Disarm              = 10
    Trigger             = 11
    
PLATFORM_SCHEMA = vol.Schema({
    vol.Required(CONF_PLATFORM):  'bwalarm',
    vol.Required(CONF_NAME):      cv.string,
    vol.Required(CONF_PENDING_TIME): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Required(CONF_TRIGGER_TIME): vol.All(vol.Coerce(int), vol.Range(min=1)),
    vol.Required(CONF_ALARM):     cv.entity_id,  # switch/group to turn on when alarming
    vol.Required(CONF_WARNING):   cv.entity_id,  # switch/group to turn on when warning
    vol.Optional(CONF_HEADSUP):   cv.entity_ids, # things to show as a headsup, not alarm on
    vol.Optional(CONF_IMMEDIATE): cv.entity_ids, # things that cause an immediate alarm
    vol.Optional(CONF_DELAYED):   cv.entity_ids, # things that allow a delay before alarm
    vol.Optional(CONF_NOTATHOME): cv.entity_ids, # things that we ignore when at home
    vol.Optional(CONF_ZONES):     cv.entity_ids  # zones
})

_LOGGER = logging.getLogger(__name__)

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    alarm = BWAlarm(hass, config)
    hass.bus.async_listen(EVENT_STATE_CHANGED, alarm.state_change_listener)
    hass.bus.async_listen(EVENT_TIME_CHANGED, alarm.time_change_listener)
    async_add_devices([alarm])
    @asyncio.coroutine
    def async_alarm_service_handler(service):
        service_name = service.service
        if service_name == 'alarm_arm_away_delay':
            code = service.data.get('code')
            alarm.alarm_arm_away_delay(str(code))
        elif service_name == 'alarm_arm_away_force':
            code = service.data.get('code')
            alarm.alarm_arm_away_force(str(code))
        elif service_name == 'alarm_arm_away_delay_force':
            code = service.data.get('code')
            alarm.alarm_arm_away_delay_force(str(code))
        elif service_name == 'alarm_arm_home_force':
            code = service.data.get('code')
            alarm.alarm_arm_home_force(str(code))
        elif service_name == 'alarm_bypass_sensor':
            sensor = service.data.get('sensor')
            alarm.alarm_bypass_sensor(sensor)   
        elif service_name == 'alarm_unbypass_sensor':
            sensor = service.data.get('sensor')
            alarm.alarm_unbypass_sensor(sensor)
        elif service_name == 'alarm_bypass_zone':
            zone = service.data.get('zone')
            alarm.alarm_bypass_zone(zone)   
        elif service_name == 'alarm_unbypass_zone':
            zone = service.data.get('zone')
            alarm.alarm_unbypass_zone(zone)   
                        
    hass.services.async_register(
                DOMAIN, "alarm_arm_away_delay", 
                async_alarm_service_handler
            )
    hass.services.async_register(
                DOMAIN, "alarm_arm_away_force", 
                async_alarm_service_handler
            )
    hass.services.async_register(
                DOMAIN, "alarm_arm_away_delay_force", 
                async_alarm_service_handler
            )
    hass.services.async_register(
                DOMAIN, "alarm_arm_home_force", 
                async_alarm_service_handler
            )
    hass.services.async_register(
                DOMAIN, "alarm_bypass_sensor", 
                async_alarm_service_handler
            )
    hass.services.async_register(
                DOMAIN, "alarm_unbypass_sensor", 
                async_alarm_service_handler
            )
    hass.services.async_register(
                DOMAIN, "alarm_bypass_zone", 
                async_alarm_service_handler
            )
    hass.services.async_register(
                DOMAIN, "alarm_unbypass_zone", 
                async_alarm_service_handler
            )
class BWAlarm(alarm.AlarmControlPanel):

    def __init__(self, hass, config):
        """ Initalize the alarm system """
        self._hass         = hass
        self._name         = config[CONF_NAME]
        self._immediate    = set(config.get(CONF_IMMEDIATE, []))
        self._delayed      = set(config.get(CONF_DELAYED, []))
        self._notathome    = set(config.get(CONF_NOTATHOME, []))
        self._allinputs    = self._immediate | self._delayed | self._notathome
        self._allsensors   = self._allinputs | set(config.get(CONF_HEADSUP, []))
        self._zones        = set(config.get(CONF_ZONES,[]))
        self._alarm        = config[CONF_ALARM]
        self._warning      = config[CONF_WARNING]
        self._pending_time = datetime.timedelta(seconds=config[CONF_PENDING_TIME])
        self._trigger_time = datetime.timedelta(seconds=config[CONF_TRIGGER_TIME])

        self._lasttrigger  = ""
        self.triggered_by = ""
        self._state        = STATE_ALARM_DISARMED
        self._returnto     = STATE_ALARM_DISARMED
        self._timeoutat    = None
        self.bypassedsensors = set()
        self.tripped_sensors = set()
        self.clearsignals()


    ### Alarm properties

    @property
    def should_poll(self) -> bool: return False
    @property
    def name(self) -> str:         return self._name
    @property
    def changed_by(self) -> str:   return self._lasttrigger
    @property
    def state(self) -> str:        return self._state
    @property
    def device_state_attributes(self):
        return {
            'immediate':        sorted(list(self.immediate)),
            'delayed':          sorted(list(self.delayed)),
            'ignored':          sorted(list(self.ignored)),
            'allsensors':       sorted(list(self._allsensors)),
            'zones':            sorted(list(self._zones)),
            'trippedsensors':   sorted(list(self.tripped_sensors)),
            'bypassedsensors':  sorted(list(self.bypassedsensors)),
            'triggeredBy':      self.triggered_by
        }


    ### Actions from the outside world that affect us, turn into enum events for internal processing

    def time_change_listener(self, eventignored):
        """ I just treat the time events as a periodic check, its simpler then (re-/un-)registration """
        if self._timeoutat is not None:
            if now() > self._timeoutat:
                self._timeoutat = None
                self.process_event(Events.Timeout)

    def state_change_listener(self, event):
        """ Something changed, we only care about things turning on at this point """
        new = event.data.get('new_state', None)
        if new is None or new.state != STATE_ON:
            return
        eid = event.data['entity_id']
        if eid in self.immediate:
            self._lasttrigger = eid
            self.triggered_by = set()
            self.process_event(Events.ImmediateTrip)
        elif eid in self.delayed:
            self._lasttrigger = eid
            self.triggered_by = set()
            self.process_event(Events.DelayedTrip)

    def alarm_disarm(self, code=None):
        self.triggered_by = code
        self.process_event(Events.Disarm)

    def alarm_arm_home(self, code=None):
        self.triggered_by = code
        self.process_event(Events.ArmHome)

    def alarm_arm_home_force(self, code=None):
        self.triggered_by = code
        self.process_event(Events.ArmHomeForce)

    def alarm_arm_away(self, code=None):
        self.triggered_by = code
        self.process_event(Events.ArmAway)

    def alarm_arm_away_force(self, code=None):
        self.triggered_by = code
        self.process_event(Events.ArmAwayForce)

    def alarm_arm_away_delay(self, code=None):
        self.triggered_by = code
        self.process_event(Events.ArmAwayDelay)

    def alarm_arm_away_delay_force(self, code=None):
        self.triggered_by = code
        self.process_event(Events.ArmAwayDelayForce)

    def alarm_trigger(self, code=None):
        self.triggered_by = code
        self.process_event(Events.Trigger)

    def alarm_bypass_sensor(self, sensor):
        _LOGGER.info("RSDATA_ALARM --> Bypass Sensor ({})".format(sensor))
        self.bypassedsensors.add(sensor)
        _LOGGER.info("Successful bypass of <{}>".format(sensor))
        self.schedule_update_ha_state()

    def alarm_unbypass_sensor(self, sensor):
        _LOGGER.info("RSDATA_ALARM --> Unbypass Sensor ({})".format(sensor))
        if self.noton(sensor):
            self.bypassedsensors.remove(sensor)
            _LOGGER.info("Successful unbypass of <{}>".format(sensor))
        else:
            self.tripped_sensors = set()
            self.tripped_sensors.add(sensor)
            _LOGGER.info("UnSuccessful unbypass - <{}>".format(self.tripped_sensors))
        self.schedule_update_ha_state()

    def alarm_bypass_zone(self, zone_eid):
        _LOGGER.info("RSDATA_ALARM --> Bypass Zone ({})".format(zone_eid))
        zone = self._hass.states.get(zone_eid)
        self.tripped_sensors = set()
        _LOGGER.info(zone)
        if zone and self._state in [STATE_ALARM_ARMED_AWAY, STATE_ALARM_ARMED_HOME, STATE_ALARM_DISARMED]:
            zone_sensors = zone.attributes['entity_id']
            _LOGGER.info("{} Sensors - <{}>".format(zone_eid, zone_sensors))
            self.bypassedsensors |= set(zone_sensors)
            self.immediate -= set(zone_sensors)
            self.delayed -= set(zone_sensors)
            self.ignored = self._allinputs - (self.immediate | self.delayed)
            _LOGGER.info("Successful bypass of {} - <{}>".format(zone_eid, zone_sensors))
            self.schedule_update_ha_state()
        else:
            self.tripped_sensors = set()
            _LOGGER.error("Something went wrong...:(")

    def alarm_unbypass_zone(self, zone_eid):
        _LOGGER.info("RSDATA_ALARM --> Unbypass Zone ({})".format(zone_eid))
        zone = self._hass.states.get(zone_eid)
        self.tripped_sensors = set()
        _LOGGER.info(zone)
        if zone and self._state in [STATE_ALARM_ARMED_AWAY, STATE_ALARM_ARMED_HOME, STATE_ALARM_DISARMED]:
            zone_sensors = set(zone.attributes['entity_id'])
            zone_sensors_not_on = set(filter(self.noton, zone_sensors))
            _LOGGER.info("{} Sensors - <{}>".format(zone_eid, zone_sensors))
            if  self._state in [STATE_ALARM_ARMED_AWAY, STATE_ALARM_ARMED_HOME]:
                if zone_sensors_not_on == zone_sensors:
                    self.bypassedsensors -= zone_sensors
                    self.immediate |= zone_sensors&self._immediate
                    self.delayed |= zone_sensors&self._delayed
                    self.ignored = self._allinputs - (self.immediate | self.delayed)
                    _LOGGER.info("Successful unbypass of {} - <{}>".format(zone_eid, zone_sensors))
                else:
                    self.tripped_sensors = zone_sensors - zone_sensors_not_on
                    _LOGGER.info("UnSuccessful unbypass - <{}>".format(self.tripped_sensors))
            else:
                _LOGGER.info("Successful unbypass of {} - <{}>".format(zone_eid, zone_sensors))
                self.bypassedsensors -= zone_sensors
            self.schedule_update_ha_state()
        else:
            self.tripped_sensors = set()
            _LOGGER.error("Something went wrong...:(")


    ### Internal processing

    def noton(self, eid):
        """ For filtering out sensors already tripped """
        return not self._hass.states.is_state(eid, STATE_ON)

    def setsignals(self, athome):
        """ Figure out what to sense and how """
        self.immediate = self._immediate - self.bypassedsensors
        self.delayed = self._delayed - self.bypassedsensors
        self.immediate = set(filter(self.noton, self.immediate))
        self.delayed = set(filter(self.noton, self.delayed))
        self.tripped_sensors = (self._immediate - self.immediate) | (self._delayed - self.delayed)
        if not athome:
            self.immediate |= self.delayed
            self.delayed = set()
        self.tripped_sensors -= self.bypassedsensors
        _LOGGER.info("Tripped Sensors - <{}>".format(self.tripped_sensors))
        _LOGGER.info("Bypassed Sensors - <{}>".format(self.bypassedsensors))
        self.ignored = self._allinputs - (self.immediate | self.delayed)

    def clearsignals(self):
        """ Clear all our signals, we aren't listening anymore """
        self.immediate = set()
        self.delayed = set()
        self.bypassedsensors = set()
        self.ignored = self._allinputs.copy()

    def process_event(self, event):
        """ 
           This is the core logic function.
           The possible states and things that can change our state are:
                 Actions:  isensor dsensor timeout arm_home arm_away disarm trigger
           Current State: 
             disarmed         X       X       X      armh     pend     *     trig
             pending(T1)      X       X      arma     X        X      dis    trig
             armed(h/a)      trig    warn     X       X        X      dis    trig
             warning(T1)      X       X      trig     X        X      dis    trig
             triggered(T2)    X       X      last     X        X      dis     *

           As the only non-timed states are disarmed, armed_home and armed_away,
           they are the only ones we can return to after an alarm.
        """
        old = self._state

        # Update state if applicable
        if event == Events.Disarm:
            self._state = STATE_ALARM_DISARMED
        elif event == Events.Trigger:
            self._state = STATE_ALARM_TRIGGERED 
        elif old == STATE_ALARM_DISARMED:
            if   event == Events.ArmHome:               self._state = STATE_ALARM_ARMED_HOME
            elif event == Events.ArmHomeForce:          self._state = STATE_ALARM_ARMED_HOME
            elif event == Events.ArmAway:               self._state = STATE_ALARM_ARMED_AWAY
            elif event == Events.ArmAwayForce:          self._state = STATE_ALARM_ARMED_AWAY
            elif event == Events.ArmAwayDelay:          self._state = STATE_ALARM_ARMED_AWAY
            elif event == Events.ArmAwayDelayForce:     self._state = STATE_ALARM_ARMED_AWAY
        elif old == STATE_ALARM_PENDING:
            if   event == Events.Timeout:               self._state = STATE_ALARM_ARMED_AWAY
            elif event == Events.ArmAwayForce:          self._state = STATE_ALARM_ARMED_AWAY
        elif old == STATE_ALARM_ARMED_HOME or \
             old == STATE_ALARM_ARMED_AWAY:
            if   event == Events.ImmediateTrip:         self._state = STATE_ALARM_TRIGGERED
            elif event == Events.DelayedTrip:           self._state = STATE_ALARM_WARNING
        elif old == STATE_ALARM_WARNING:
            if   event == Events.Timeout:               self._state = STATE_ALARM_TRIGGERED
        elif old == STATE_ALARM_TRIGGERED:
            if   event == Events.Timeout:               self._state = self._returnto
            elif event == Events.DelayedTrip:           self._state = STATE_ALARM_TRIGGERED

        new = self._state
        if old != new or new == STATE_ALARM_TRIGGERED:
            _LOGGER.info("RSDATA_ALARM --> Changing from {} to {} ({})".format(old, new, event))
            # Things to do on entering state
            if new == STATE_ALARM_WARNING:
                _LOGGER.info("RSDATA_ALARM --> Turning on warning by {}".format(self._lasttrigger))
                input_boolean.turn_on(self._hass, self._warning)
                self._timeoutat = now() + self._pending_time
            elif new == STATE_ALARM_TRIGGERED:
                _LOGGER.info("RSDATA_ALARM --> Triggered alarm by {}".format(self._lasttrigger))
                input_boolean.turn_on(self._hass, self._alarm)
                self._timeoutat = now() + self._trigger_time
            elif new == STATE_ALARM_DISARMED:
                _LOGGER.info("RSDATA_ALARM --> Disarming alarm")
                self._returnto = STATE_ALARM_DISARMED
                self.clearsignals()
            elif new == STATE_ALARM_ARMED_AWAY:
                _LOGGER.info("RSDATA_ALARM --> Attempt Arm (Away)")
                self._returnto = STATE_ALARM_ARMED_AWAY
                self.setsignals(False)
                if   event == Events.ArmAway or  (event == Events.Timeout and old == STATE_ALARM_PENDING):
                    if self.tripped_sensors != set():
                        self._state = STATE_ALARM_DISARMED
                        self.clearsignals()
                elif event == Events.ArmAwayForce or (event == Events.Timeout and old == STATE_ALARM_TRIGGERED):
                    self.bypassedsensors|=self.tripped_sensors
                elif event == Events.ArmAwayDelayForce:
                    self.bypassedsensors|=self.tripped_sensors
                    self._state = STATE_ALARM_PENDING
                    self._timeoutat = now() + self._pending_time
                elif event == Events.ArmAwayDelay:
                    if self.tripped_sensors != set():
                        self._state = STATE_ALARM_DISARMED
                        self.clearsignals()
                    else:
                        self._state = STATE_ALARM_PENDING
                        self._timeoutat = now() + self._pending_time
            elif new == STATE_ALARM_ARMED_HOME:
                _LOGGER.info("RSDATA_ALARM --> Attempt Arm (Home)")
                self._returnto = STATE_ALARM_ARMED_HOME
                self.bypassedsensors|=self._notathome
                self.setsignals(True)
                if   event == Events.ArmHome:
                    if self.tripped_sensors != set():
                        self._state = STATE_ALARM_DISARMED
                        self.clearsignals()
                elif event == Events.ArmHomeForce or (event == Events.Timeout and old == STATE_ALARM_TRIGGERED):
                    self.bypassedsensors|=self.tripped_sensors

            # Things to do on leaving state
            if old == STATE_ALARM_WARNING or old == STATE_ALARM_PENDING:
                _LOGGER.info("RSDATA_ALARM --> Turning off warning")
                input_boolean.turn_off(self._hass, self._warning)
            elif old == STATE_ALARM_TRIGGERED and old != new:
                _LOGGER.info("RSDATA_ALARM --> Turning off alarm")
                input_boolean.turn_off(self._hass, self._alarm)

            # Let HA know that something changed
        self.schedule_update_ha_state()
