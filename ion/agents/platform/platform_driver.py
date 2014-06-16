#!/usr/bin/env python

"""
@package ion.agents.platform.platform_driver
@file    ion/agents/platform/platform_driver.py
@author  Carlos Rueda
@brief   Base classes supporting platform drivers.
"""

__author__ = 'Carlos Rueda'



from pyon.public import log
import logging

from copy import deepcopy

from ion.agents.platform.platform_driver_event import DriverEvent
from ion.agents.platform.platform_driver_event import StateChangeDriverEvent
from ion.agents.platform.platform_driver_event import AsyncAgentEvent
from ion.agents.platform.exceptions import PlatformDriverException

from pyon.agent.common import BaseEnum
from pyon.agent.instrument_fsm import ThreadSafeFSM
from pyon.agent.instrument_fsm import FSMError
from ion.agents.platform.exceptions import PlatformConnectionException
from ion.agents.platform.util.network_util import NetworkUtil


class PlatformDriverState(BaseEnum):
    """
    Platform driver states
    """
    UNCONFIGURED     = 'PLATFORM_DRIVER_STATE_UNCONFIGURED'
    DISCONNECTED     = 'PLATFORM_DRIVER_STATE_DISCONNECTED'
    CONNECTED        = 'PLATFORM_DRIVER_STATE_CONNECTED'


class PlatformDriverEvent(BaseEnum):
    """
    Base events for driver state machines.
    Subclasses will typically extend this class to add events for the
    CONNECTED state.
    """
    ENTER            = 'PLATFORM_DRIVER_EVENT_ENTER'
    EXIT             = 'PLATFORM_DRIVER_EVENT_EXIT'

    CONFIGURE        = 'PLATFORM_DRIVER_EVENT_CONFIGURE'
    CONNECT          = 'PLATFORM_DRIVER_EVENT_CONNECT'
    CONNECTION_LOST  = 'PLATFORM_DRIVER_CONNECTION_LOST'
    DISCONNECT       = 'PLATFORM_DRIVER_EVENT_DISCONNECT'

    # Events for the CONNECTED state:
    PING             = 'PLATFORM_DRIVER_PING'
    GET              = 'PLATFORM_DRIVER_GET'
    SET              = 'PLATFORM_DRIVER_SET'
    EXECUTE          = 'PLATFORM_DRIVER_EXECUTE'


class PlatformDriverCapability(BaseEnum):
    """
    Subclasses will indicate the particular set of capabilities to be exposed.
    """
    pass


class PlatformDriver(object):
    """
    A platform driver handles a particular platform in a platform network.
    This base class provides a common interface and supporting functionality.
    """

    def __init__(self, pnode, event_callback):
        """
        Creates a PlatformDriver instance.

        @param pnode           Root PlatformNode defining the platform network
                               rooted at this platform.
        @param event_callback  Listener of events generated by this driver
        """

        #
        # NOTE the "pnode" parameter may be not very "standard" but it is the
        # current convenient mechanism that captures the overall definition
        # of the corresponding platform (most of which coming from configuration)
        #

        self._pnode = pnode
        self._send_event = event_callback

        self._platform_id = self._pnode.platform_id
        if self._pnode.parent:
            self._parent_platform_id = self._pnode.parent.platform_id
        else:
            self._parent_platform_id = None

        self._platform_attributes = \
            dict((a.attr_id, a.defn) for a in self._pnode.attrs.itervalues())

        if log.isEnabledFor(logging.DEBUG):
            log.debug("%r: PlatformDriver constructor called: pnode:\n%s\n"
                      "_platform_attributes=%s",
                      self._platform_id,
                      NetworkUtil._dump_pnode(self._pnode, include_subplatforms=False),
                      self._platform_attributes)

        self._driver_config = None
        self._resource_schema = {}
        
        # The parameter dictionary.
        self._param_dict = {}

        # construct FSM and start it with initial state UNCONFIGURED:
        self._construct_fsm()
        self._fsm.start(PlatformDriverState.UNCONFIGURED)

    def get_resource_capabilities(self, current_state=True):
        """
        """
        res_cmds = self._fsm.get_events(current_state)
        res_cmds = self._filter_capabilities(res_cmds)
        res_params = self._param_dict.keys()

        return [res_cmds, res_params]

    def _filter_capabilities(self, events):
        """
        Typically overwritten in subclass.
        """
        events_out = [x for x in events if PlatformDriverCapability.has(x)]
        return events_out

    def get_resource_state(self, *args, **kwargs):
        """
        Return the current state of the driver.
        @retval str current driver state.
        """
        return self._fsm.get_current_state()

    def get_resource(self, *args, **kwargs):
        """
        """
        return self._fsm.on_event(PlatformDriverEvent.GET, *args, **kwargs)

    def set_resource(self, *args, **kwargs):
        """
        """
        return self._fsm.on_event(PlatformDriverEvent.SET, *args, **kwargs)

    def execute_resource(self, resource_cmd, *args, **kwargs):
        """
        Platform agent calls this directly to trigger the execution of a
        resource command. The actual action occurs in execute.
        """
        return self._fsm.on_event(PlatformDriverEvent.EXECUTE, resource_cmd, *args, **kwargs)

    def _get_platform_attributes(self):
        """
        Gets a dict of the attribute definitions in this platform as given at
        construction time (from pnode parameter).
        """
        return self._platform_attributes

    def validate_driver_configuration(self, driver_config):
        """
        Called by configure so a subclass can perform any needed additional
        validation of the provided configuration.
        Nothing is done in this base class. Note that basic validation is
        done by PlatformAgent prior to creating/configuring the driver.

        @param driver_config Driver configuration.

        @raise PlatformDriverException Error in driver configuration.
        """
        pass

    def configure(self, driver_config):
        """
        Configures this driver. In this base class it basically
        calls validate_driver_configuration and then assigns the given
        config to self._driver_config.

        @param driver_config Driver configuration.
        """
        if log.isEnabledFor(logging.DEBUG):
            log.debug("%r: configure: %s" % (self._platform_id, str(driver_config)))

        self.validate_driver_configuration(driver_config)
        self._driver_config = driver_config
        #self._param_dict = deepcopy(self._driver_config.get('attributes',{}))
        
    def get_config_metadata(self):
        """
        """
        return deepcopy(self._resource_schema)

    def connect(self, recursion=None):
        """
        To be implemented by subclass.
        Establishes communication with the platform device.

        @raise PlatformConnectionException
        """
        raise NotImplementedError()  #pragma: no cover

    def disconnect(self, recursion=None):
        """
        To be implemented by subclass.
        Ends communication with the platform device.

        @raise PlatformConnectionException
        """
        raise NotImplementedError()  #pragma: no cover

    def ping(self):
        """
        To be implemented by subclass.
        Verifies communication with external platform returning "PONG" if
        this verification completes OK.

        @retval "PONG"

        @raise PlatformConnectionException  If the connection to the external
               platform is lost.
        """
        raise NotImplementedError()  #pragma: no cover

    def get_attribute_values(self, attrs):
        """
        To be implemented by subclass.
        Returns the values for specific attributes since a given time for
        each attribute.

        @param attrs     [(attrName, from_time), ...] desired attributes.
                         from_time Assummed to be in the format basically described by
                         pyon's get_ion_ts function, "a str representing an
                         integer number, the millis in UNIX epoch."

        @retval {attrName : [(attrValue, timestamp), ...], ...}
                dict indexed by attribute name with list of (value, timestamp)
                pairs. Timestamps in same format as from_time.

        @raise PlatformConnectionException  If the connection to the external
               platform is lost.
        """
        raise NotImplementedError()  #pragma: no cover

    def set_attribute_values(self, attrs):
        """
        To be implemented by subclass.
        Sets values for writable attributes in this platform.

        @param attrs 	[(attrName, attrValue), ...] 	List of attribute values

        @retval {attrName : [(attrValue, timestamp), ...], ...}
                dict with a list of (value,timestamp) pairs for each attribute
                indicated in the input. Returned timestamps indicate the time when the
                value was set. Each timestamp is "a str representing an
                integer number, the millis in UNIX epoch" to
                align with description of pyon's get_ion_ts function.

        @raise PlatformConnectionException  If the connection to the external
               platform is lost.
        """
        #
        # TODO Any needed alignment with the instrument case?
        #
        raise NotImplementedError()  #pragma: no cover

    def execute(self, cmd, *args, **kwargs):
        """
        Executes the given command.
        Subclasses can override to execute particular commands or delegate to
        its super class. However, note that this base class raises
        NotImplementedError.

        @param cmd     command
        @param args    command's args
        @param kwargs  command's kwargs

        @return  result of the execution

        @raise PlatformConnectionException  If the connection to the external
               platform is lost.
        """
        raise NotImplementedError()  # pragma: no cover

    def get(self, *args, **kwargs):
        """
        Gets the values of the requested attributes.
        Subclasses can override to get particular attributes and
        delegate to this base implementation to handle common attributes.

        @param args    get's args
        @param kwargs  get's kwargs

        @return  result of the retrieval.

        @raise PlatformConnectionException  If the connection to the external
               platform is lost.
        """
        raise NotImplementedError()  # pragma: no cover

    def destroy(self):
        """
        Stops all activity done by the driver. Nothing done in this class.
        """
        pass

    def _notify_driver_event(self, driver_event):
        """
        Convenience method for subclasses to send a driver event to
        corresponding platform agent.

        @param driver_event a DriverEvent object.
        """
        log.debug("%r: _notify_driver_event: %s", self._platform_id, driver_event)

        self._send_event(driver_event)

    def get_external_checksum(self):
        """
        To be implemented by subclass.
        Returns the checksum of the external platform associated with this
        driver.

        @return SHA1 hash value as string of hexadecimal digits.

        @raise PlatformConnectionException  If the connection to the external
               platform is lost.
        """
        raise NotImplementedError()  #pragma: no cover

    def get_driver_state(self):
        """
        Returns the current FSM state.
        """
        return self._fsm.get_current_state()

    #####################################################################
    # Supporting method for handling connection lost in CONNECT handlers
    #####################################################################

    def _connection_lost(self, cmd, args, kwargs, exc=None):
        """
        Supporting method to be called by any CONNECTED handler right after
        detecting that the connection with the external platform device has
        been lost. It does a regular disconnect() and notifies the agent about
        the lost connection. Note that the call to disconnect() itself may
        throw some additional exception very likely caused by the fact that
        the connection is lost--this exception is just logged out but ignored.

        All parameters are for logging purposes.

        @param cmd     string indicating the command that was attempted
        @param args    args of the command that was attempted
        @param kwargs  kwargs of the command that was attempted
        @param exc     associated exception (if any),

        @return (next_state, result) suitable as the return of the FSM
                handler where the connection lost was detected. The
                next_state will always be PlatformDriverState.DISCONNECTED.
        """
        log.debug("%r: (LC) _connection_lost: cmd=%s, args=%s, kwargs=%s, exc=%s",
                  self._platform_id, cmd, args, kwargs, exc)

        # NOTE I have this import here as a quick way to avoid circular imports
        # (note that platform_agent also imports elements in this module)
        # TODO better to move some basic definitions to separate modules.
        from ion.agents.platform.platform_agent import PlatformAgentEvent

        result = None
        try:
            result = self.disconnect()

        except Exception as e:
            # just log a message
            log.debug("%r: (LC) ignoring exception while calling disconnect upon"
                      " lost connection: %s", self._platform_id, e)

        # in any case, notify the agent about the lost connection and
        # transition to DISCONNECTED:
        self._notify_driver_event(AsyncAgentEvent(PlatformAgentEvent.LOST_CONNECTION))

        next_state = PlatformDriverState.DISCONNECTED

        return next_state, result

    ##############################################################
    # FSM event handlers.
    ##############################################################

    def _common_state_enter(self, *args, **kwargs):
        """
        Common work upon every state entry.
        """
        state = self.get_driver_state()
        log.debug('%r: driver entering state: %s', self._platform_id, state)

        self._notify_driver_event(StateChangeDriverEvent(state))

    def _common_state_exit(self, *args, **kwargs):
        """
        Common work upon every state exit.
        Nothing done in this base class.
        """

    ##############################################################
    # UNCONFIGURED event handlers.
    ##############################################################

    def _handler_unconfigured_configure(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        driver_config = kwargs.get('driver_config', None)
        if driver_config is None:
            raise FSMError('configure: missing driver_config argument')

        try:
            result = self.configure(driver_config)
            next_state = PlatformDriverState.DISCONNECTED
        except PlatformDriverException as e:
            result = None
            next_state = None
            log.error("Error in platform driver configuration", e)

        return next_state, result

    ##############################################################
    # DISCONNECTED event handlers.
    ##############################################################

    def _handler_disconnected_connect(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        recursion = kwargs.get('recursion', None)

        self.connect(recursion=recursion)
        result = next_state = PlatformDriverState.CONNECTED

        return next_state, result

    def _handler_disconnected_disconnect(self, *args, **kwargs):
        """
        We allow the DISCONNECT event in DISCONNECTED state for convenience,
        in particular it facilitates the overall handling of the connection_lost
        event, which is processed by a subsequent call to disconnect from the
        platform agent. The handler here does nothing.
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        return None, None

    ###########################################################################
    # CONNECTED event handlers.
    # Except for the explicit disconnect and connection_lost handlers, the
    # CONNECTED handlers (here and in subclasses) should directly catch any
    # PlatformConnectionException to call _connection_lost.
    ###########################################################################

    def _handler_connected_disconnect(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        recursion = kwargs.get('recursion', None)

        result = self.disconnect(recursion=recursion)
        next_state = PlatformDriverState.DISCONNECTED

        return next_state, result

    def _handler_connected_connection_lost(self, *args, **kwargs):
        """
        The connection was lost (as opposed to a normal disconnect request).
        Here we do the regular disconnect but also notify the platform agent
        about the lost connection.

        NOTE: this handler in the FSM is provided in case there is a need to
        directly trigger the associated transition along with the associated
        notification to the agent. However, the typical case is that a CONNECTED
        handler dealing with commands will catch any PlatformConnectionException
        to call _connection_lost directly.
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        # just use our supporting method:
        return self._connection_lost(PlatformDriverEvent.CONNECTION_LOST, args, kwargs)

    def _handler_connected_ping(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        try:
            result = self.ping()
            return None, result

        except PlatformConnectionException as e:
            return self._connection_lost(PlatformDriverEvent.PING, args, kwargs, e)

    def _handler_connected_get(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        try:
            result = self.get(*args, **kwargs)
            return None, result

        except PlatformConnectionException as e:
            return self._connection_lost(PlatformDriverEvent.GET, args, kwargs, e)

    def _handler_connected_set(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        attrs = kwargs.get('attrs', None)
        if attrs is None:
            raise FSMError('set_attribute_values: missing attrs argument')

        try:
            result = self.set_attribute_values(attrs)
            return None, result

        except PlatformConnectionException as e:
            return self._connection_lost(PlatformDriverEvent.SET, args, kwargs, e)

    def _handler_connected_execute(self, *args, **kwargs):
        """
        """
        if log.isEnabledFor(logging.TRACE):  # pragma: no cover
            log.trace("%r/%s args=%s kwargs=%s" % (
                      self._platform_id, self.get_driver_state(),
                      str(args), str(kwargs)))

        if len(args) == 0:
            raise FSMError('execute_resource: missing resource_cmd argument')

        try:
            result = self.execute(*args, **kwargs)
            return None, result

        except PlatformConnectionException as e:
            return self._connection_lost(PlatformDriverEvent.EXECUTE, args, kwargs, e)

    ##############################################################
    # Platform driver FSM setup
    ##############################################################

    def _construct_fsm(self, states=PlatformDriverState,
                       events=PlatformDriverEvent,
                       enter_event=PlatformDriverEvent.ENTER,
                       exit_event=PlatformDriverEvent.EXIT):
        """
        Constructs the FSM for the driver. The preparations here are mostly
        related with the UNCONFIGURED, DISCONNECTED, and CONNECTED state
        transitions, with some common handlers for the CONNECTED state.
        Subclasses can override to indicate specific parameters and add new
        handlers (typically for the CONNECTED state).
        """
        log.debug("constructing base platform driver FSM")

        self._fsm = ThreadSafeFSM(states, events, enter_event, exit_event)

        for state in PlatformDriverState.list():
            self._fsm.add_handler(state, enter_event, self._common_state_enter)
            self._fsm.add_handler(state, exit_event, self._common_state_exit)

        # UNCONFIGURED state event handlers:
        self._fsm.add_handler(PlatformDriverState.UNCONFIGURED, PlatformDriverEvent.CONFIGURE, self._handler_unconfigured_configure)

        # DISCONNECTED state event handlers:
        self._fsm.add_handler(PlatformDriverState.DISCONNECTED, PlatformDriverEvent.CONNECT, self._handler_disconnected_connect)
        self._fsm.add_handler(PlatformDriverState.DISCONNECTED, PlatformDriverEvent.DISCONNECT, self._handler_disconnected_disconnect)

        # CONNECTED state event handlers:
        self._fsm.add_handler(PlatformDriverState.CONNECTED, PlatformDriverEvent.DISCONNECT, self._handler_connected_disconnect)
        self._fsm.add_handler(PlatformDriverState.CONNECTED, PlatformDriverEvent.CONNECTION_LOST, self._handler_connected_connection_lost)

        self._fsm.add_handler(PlatformDriverState.CONNECTED, PlatformDriverEvent.PING, self._handler_connected_ping)
        self._fsm.add_handler(PlatformDriverState.CONNECTED, PlatformDriverEvent.GET, self._handler_connected_get)
        self._fsm.add_handler(PlatformDriverState.CONNECTED, PlatformDriverEvent.SET, self._handler_connected_set)
        self._fsm.add_handler(PlatformDriverState.CONNECTED, PlatformDriverEvent.EXECUTE, self._handler_connected_execute)
