import base64
import json
from enum import Enum, IntEnum
from dataclasses import dataclass
from typing import Optional
from pyopendroneid import opendroneid
from pyopendroneid.helper import parseOpenDroneID, datify_opendroneid_dict
from dtproto_receiver import dri_message_pb2, DriMessage

class Tech(Enum):
    BT4 = "B4"
    BT5 = "B5"
    WIFI_NAN = "WN"
    WIFI_BEACON = "WB"


class OdidType(IntEnum):
    BASIC_ID = opendroneid.ODID_MESSAGETYPE_BASIC_ID
    LOCATION = opendroneid.ODID_MESSAGETYPE_LOCATION
    AUTH = opendroneid.ODID_MESSAGETYPE_AUTH
    SELF_ID = opendroneid.ODID_MESSAGETYPE_SELF_ID
    SYSTEM = opendroneid.ODID_MESSAGETYPE_SYSTEM
    OPERATOR_ID = opendroneid.ODID_MESSAGETYPE_OPERATOR_ID
    PACKED = opendroneid.ODID_MESSAGETYPE_PACKED
    INVALID = opendroneid.ODID_MESSAGETYPE_INVALID

    @classmethod
    def get_type(cls, type_id: int) -> "OdidType":
        """get_type accepts first byte"""
        try:
            return OdidType((type_id & 0xF0) >> 4)
        except Exception:
            return OdidType.INVALID
        
@dataclass
class DriReaderInfo:
    mac: bytes  # should be standard 6-byte MAC address
    tech: Tech  # transmission technology and format
    odid_type: OdidType  # message type
    rssi: int
    counter: int  # message counter for deduplication (beware ADSx do not support this hence -1)
    recv_id: int = 0  # unique identifier of the chip on the module that received the message

    @classmethod
    def from_message(
        cls, dri_message: dri_message_pb2.DriMessage
    ) -> Optional["DriReaderInfo"]:
        """Create DriReaderInfo from a DriMessage"""
        recv_id = dri_message.receiver_data.component_id << 4 | dri_message.receiver_data.receiver_type

        if dri_message.HasField("odid_payload"):
            odid_type = OdidType.get_type(dri_message.odid_payload.encoded_message[0])
            counter = dri_message.odid_payload.counter

            if dri_message.odid_payload.WhichOneof("transmission_info") == "wifi_beacon_info":
                return DriReaderInfo(
                    recv_id=recv_id,
                    odid_type=odid_type,
                    counter=counter,
                    mac=dri_message.odid_payload.wifi_beacon_info.mac,
                    rssi=dri_message.odid_payload.wifi_beacon_info.rssi,
                    tech=Tech.WIFI_BEACON,
                )
            elif dri_message.odid_payload.WhichOneof("transmission_info") == "wifi_nan_info":
                return DriReaderInfo(
                    recv_id=recv_id,
                    odid_type=odid_type,
                    counter=counter,
                    mac=dri_message.odid_payload.wifi_nan_info.mac,
                    rssi=dri_message.odid_payload.wifi_nan_info.rssi,
                    tech=Tech.WIFI_NAN,
                )
            elif dri_message.odid_payload.WhichOneof("transmission_info") == "bluetooth_legacy_info":
                return DriReaderInfo(
                    recv_id=recv_id,
                    odid_type=odid_type,
                    counter=counter,
                    mac=dri_message.odid_payload.bluetooth_legacy_info.mac,
                    rssi=dri_message.odid_payload.bluetooth_legacy_info.rssi,
                    tech=Tech.BT4,
                )
            elif dri_message.odid_payload.WhichOneof("transmission_info") == "bluetooth_long_range_info":
                return DriReaderInfo(
                    recv_id=recv_id,
                    odid_type=odid_type,
                    counter=counter,
                    mac=dri_message.odid_payload.bluetooth_long_range_info.mac,
                    rssi=dri_message.odid_payload.bluetooth_long_range_info.rssi,
                    tech=Tech.BT5,
                )
            else:
                raise ValueError(
                    "DRI transmission_info none of "
                    "wifi_beacon_info, wifi_nan_info, bluetooth_legacy_info, bluetooth_long_range_info"
                )
        return None
        
def dt_odid_parser(dri_message: dri_message_pb2.DriMessage) -> None:
    messageType, odid_parsed = parseOpenDroneID(dri_message.odid_payload.encoded_message)
    if odid_parsed:
        odid_parsed = datify_opendroneid_dict(odid_parsed)
    dri_info = DriReaderInfo.from_message(dri_message)
    if dri_info is None:
        print("Could not extract the info")
        return
    serDict = {
        "mac": dri_info.mac.hex(":"),
        "counter": dri_info.counter,
        "rssi": dri_info.rssi,
        "tech": dri_info.tech.value,
        "recv_id": dri_info.recv_id,
        "msg_type": dri_info.odid_type.value,
        "odid": odid_parsed,
        "odid_raw": base64.b64encode(dri_message.odid_payload.encoded_message),
    }
    return serDict