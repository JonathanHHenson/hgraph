from typing import Type, TypeVar, Optional, _GenericAlias

from hg._types._scalar_type_meta_data import HgScalarTypeMetaData
from hg._types._time_series_meta_data import HgTimeSeriesTypeMetaData, HgTypeMetaData


__all__ = ("HgTSDTypeMetaData", "HgTSDOutTypeMetaData",)


class HgTSDTypeMetaData(HgTimeSeriesTypeMetaData):

    key_tp: HgScalarTypeMetaData
    value_tp: HgTimeSeriesTypeMetaData

    def __init__(self, key_tp: HgScalarTypeMetaData, value_tp: HgTimeSeriesTypeMetaData):
        self.value_tp = value_tp
        self.key_tp = key_tp

    @property
    def is_resolved(self) -> bool:
        return self.value_tp.is_resolved and self.key_tp.is_resolved

    @property
    def py_type(self) -> Type:
        from hg._types._tsd_type import TSD
        return TSD[self.key_tp.py_type, self.value_tp.py_type]

    def resolve(self, resolution_dict: dict[TypeVar, "HgTypeMetaData"]) -> "HgTypeMetaData":
        if self.is_resolved:
            return self
        else:
            return type(self)(self.key_tp.resolve(resolution_dict), self.value_tp.resolve(resolution_dict))

    def build_resolution_dict(self, resolution_dict: dict[TypeVar, "HgTypeMetaData"], wired_type: "HgTypeMetaData"):
        super().build_resolution_dict(resolution_dict, wired_type)
        wired_type: HgTSDTypeMetaData
        self.value_tp.build_resolution_dict(resolution_dict, wired_type.value_tp)
        self.key_tp.build_resolution_dict(resolution_dict, wired_type.key_tp)

    @classmethod
    def parse(cls, value) -> Optional["HgTypeMetaData"]:
        from hg._types._tsd_type import TimeSeriesDictInput
        if isinstance(value, _GenericAlias) and value.__origin__ is TimeSeriesDictInput:
            return HgTSDTypeMetaData(HgScalarTypeMetaData.parse(value.__args__[0]),
                                     HgTimeSeriesTypeMetaData.parse(value.__args__[1]))

    def __eq__(self, o: object) -> bool:
        return type(o) is HgTSDTypeMetaData and self.key_tp == o.key_tp and self.value_tp == o.value_tp

    def __str__(self) -> str:
        return f'TSD[{str(self.key_tp)}, {str(self.value_tp)}]'

    def __repr__(self) -> str:
        return f'HgTSDTypeMetaData({repr(self.key_tp)}, {repr(self.value_tp)})'

    def __hash__(self) -> int:
        from hg._types._tsd_type import TSD
        return hash(TSD) ^ hash(self.value_tp) ^ hash(self.key_tp)


class HgTSDOutTypeMetaData(HgTSDTypeMetaData):

    @classmethod
    def parse(cls, value) -> Optional["HgTypeMetaData"]:
        from hg._types._tsd_type import TimeSeriesDictOutput
        if isinstance(value, _GenericAlias) and value.__origin__ is TimeSeriesDictOutput:
            return HgTSDOutTypeMetaData(HgScalarTypeMetaData.parse(value.__args__[0]),
                                        HgTimeSeriesTypeMetaData.parse(value.__args__[1]))

    def __eq__(self, o: object) -> bool:
        return type(o) is HgTSDOutTypeMetaData and self.key_tp == o.key_tp and self.value_tp == o.value_tp

    def __str__(self) -> str:
        return f'TSD_OUT[{str(self.key_tp)}, {str(self.value_tp)}]'

    def __repr__(self) -> str:
        return f'HgTSDOutTypeMetaData({repr(self.key_tp)}, {repr(self.value_tp)})'
