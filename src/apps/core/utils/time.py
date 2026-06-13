import typing
import datetime
import jdatetime


def convert_to_jalali(date: datetime.date) -> typing.Optional[jdatetime.date]:
    if not date:
        return None
    return jdatetime.datetime.fromgregorian(date=date).date()


def convert_to_gregorian(date: datetime.date) -> typing.Optional[jdatetime.date]:
    if not date:
        return None
    return jdatetime.date(date.year, date.month, date.day).togregorian()
