import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from zipfile import ZipFile

from transit_odp.avl.post_publishing_checks.constants import ErrorCategory, SirivmField
from transit_odp.avl.post_publishing_checks.daily.results import (
    MiscFieldPPC,
    ValidationResult,
)
from transit_odp.avl.post_publishing_checks.models import (
    MonitoredVehicleJourney,
    VehicleActivity,
)
from transit_odp.common.utils.choice_enum import ChoiceEnum
from transit_odp.common.xmlelements.exceptions import (
    NoElement,
    TooManyElements,
    XMLAttributeError,
)
from transit_odp.organisation.models import TXCFileAttributes
from transit_odp.timetables.transxchange import (
    TransXChangeDocument,
    TransXChangeElement,
)

logger = logging.getLogger(__name__)


class DayOfWeek(ChoiceEnum):
    monday = "Monday"
    tuesday = "Tuesday"
    wednesday = "Wednesday"
    thursday = "Thursday"
    friday = "Friday"
    saturday = "Saturday"
    sunday = "Sunday"

    @classmethod
    def from_weekday_int(cls, weekday: int) -> "DayOfWeek":
        """Create DayOfWeek object from zero-based integer, compatible with
        library method date.weekday()
        """
        map = {
            0: cls.monday,
            1: cls.tuesday,
            2: cls.wednesday,
            3: cls.thursday,
            4: cls.friday,
            5: cls.saturday,
            6: cls.sunday,
        }
        return map[weekday]


@dataclass
class TxcVehicleJourney:
    vehicle_journey: TransXChangeElement
    txc_xml: TransXChangeDocument


class VehicleJourneyFinder:
    def get_vehicle_journey_ref(self, mvj: MonitoredVehicleJourney) -> Optional[str]:
        framed_vehicle_journey_ref = mvj.framed_vehicle_journey_ref
        if framed_vehicle_journey_ref is not None:
            return framed_vehicle_journey_ref.dated_vehicle_journey_ref
        return None

    def check_operator_and_line_present(
        self, activity: VehicleActivity, result: ValidationResult
    ) -> bool:
        mvj = activity.monitored_vehicle_journey
        if mvj.operator_ref is None:
            result.add_error(
                ErrorCategory.GENERAL,
                "OperatorRef missing in SIRI-VM VehicleActivity",
            )
            return False

        if mvj.line_ref is None:
            result.add_error(
                ErrorCategory.GENERAL, "LineRef missing in SIRI-VM VehicleActivity"
            )
            return False
        return True

    def get_txc_file_metadata(
        self, noc: str, line_name: str, result: ValidationResult
    ) -> List[TXCFileAttributes]:
        """Get a list of published datasets with live revisions that match operator
        ref and line name.
        """
        logger.info(
            f"Get published timetable files matching NOC {noc} and LineName {line_name}"
        )
        txc_file_attrs = list(
            TXCFileAttributes.objects.add_revision_details()
            .get_active_live_revisions()
            .filter_by_noc_and_line_name(noc, line_name)
            .select_related("revision")
        )

        if len(txc_file_attrs) == 0:
            result.add_error(
                ErrorCategory.GENERAL,
                f"No published TXC files found matching NOC {noc} and "
                f"line name {line_name}",
            )

        logger.debug(
            f"Found {len(txc_file_attrs)} timetable files matching NOC and LineName"
        )
        for idx, txc_file in enumerate(txc_file_attrs):
            logger.debug(
                f"{idx + 1}: Dataset id {txc_file.dataset_id} "
                f"filename {txc_file.filename}"
            )

        return txc_file_attrs

    def check_same_dataset(
        self,
        txc_file_attrs: List[TXCFileAttributes],
        mvj: MonitoredVehicleJourney,
        result: ValidationResult,
    ) -> bool:
        dataset_ids = {txc.dataset_id for txc in txc_file_attrs}
        consistent_data = len(dataset_ids) == 1
        if consistent_data:
            result.set_misc_value(MiscFieldPPC.BODS_DATASET_ID, dataset_ids.pop())
            result.set_txc_value(SirivmField.OPERATOR_REF, mvj.operator_ref)
            result.set_matches(SirivmField.OPERATOR_REF)
            result.set_txc_value(SirivmField.LINE_REF, mvj.line_ref)
            result.set_matches(SirivmField.LINE_REF)
        else:
            logger.error("Matching TXC files belong to different datasets!\n")
            result.add_error(
                ErrorCategory.GENERAL,
                "Matched OperatorRef and LineRef in more than one dataset",
            )

        return consistent_data

    def get_corresponding_timetable_xml_files(
        self, txc_file_attrs: List[TXCFileAttributes]
    ) -> List[TransXChangeDocument]:
        """Get entire XML content for each TXC object."""
        timetables: List[TransXChangeDocument] = []
        upload_file = txc_file_attrs[0].revision.upload_file
        if Path(upload_file.name).suffix == ".xml":
            with upload_file.open("rb") as fp:
                timetables.append(TransXChangeDocument(fp))
        else:
            with ZipFile(upload_file) as zin:
                txc_filenames = [txc.filename for txc in txc_file_attrs]
                for filename in zin.namelist():
                    if filename in txc_filenames:
                        with zin.open(filename, "r") as fp:
                            timetables.append(TransXChangeDocument(fp))

        logger.info(
            f"Found {len(timetables)} out of {len(txc_file_attrs)} TXC XML files"
        )
        return timetables

    def filter_by_operating_period(
        self,
        activity_date: datetime.date,
        txc_xml: List[TransXChangeDocument],
        result: ValidationResult,
    ) -> bool:
        """Filter list of timetable files down to those in which the VehicleActivity
        date is inside the Service-level OperatingPeriod. Returns the list in place
        with non-matching timetables removed.
        """
        for idx in range(len(txc_xml) - 1, -1, -1):
            operating_period_start = txc_xml[idx].get_operating_period_start_date()
            error_msg = None
            if not operating_period_start:
                error_msg = (
                    f"Ignoring timetable {txc_xml[idx].get_file_name()} with no "
                    "OperatingPeriod"
                )
                result.add_error(ErrorCategory.GENERAL, error_msg)
                logger.info(error_msg)
            else:
                try:
                    start_date = datetime.date.fromisoformat(
                        operating_period_start[0].text
                    )
                except ValueError:
                    error_msg = (
                        f"Ignoring timetable {txc_xml[idx].get_file_name()} with "
                        "incorrectly formatted OperatingPeriod.StartDate"
                    )
                    result.add_error(ErrorCategory.GENERAL, error_msg)

                if error_msg is None:
                    operating_period_end = txc_xml[idx].get_operating_period_end_date()
                    try:
                        end_date = (
                            None
                            if not operating_period_end
                            else datetime.date.fromisoformat(
                                operating_period_end[0].text
                            )
                        )
                    except ValueError:
                        error_msg = (
                            f"Ignoring timetable {txc_xml[idx].get_file_name()} with "
                            "incorrectly formatted OperatingPeriod.EndDate"
                        )
                        result.add_error(ErrorCategory.GENERAL, error_msg)

                    if error_msg is None:
                        if start_date <= activity_date:
                            if end_date is None or end_date >= activity_date:
                                continue

                        end_date_str = "-" if end_date is None else str(end_date)
                        logger.debug(
                            f"Filtering out timetable {txc_xml[idx].get_file_name()} "
                            f"with OperatingPeriod ({start_date} to {end_date_str})"
                        )
            txc_xml.pop(idx)

        logger.info(
            f"Filtering by OperatingPeriod left {len(txc_xml)} timetable TXC " "files"
        )
        if len(txc_xml) == 0:
            result.add_error(
                ErrorCategory.GENERAL,
                "No timetables found with VehicleActivity date in OperatingPeriod",
            )
            return False

        return True

    def filter_by_journey_code(
        self,
        txc_xml: List[TransXChangeDocument],
        vehicle_journey_ref: str,
        result: ValidationResult,
    ) -> List[TxcVehicleJourney]:
        """Filter list of timetable files down to individual journeys matching the
        passed vehicle journey ref. Returns list of matching journeys coupled with their
        parent timetable file.
        """
        matching_journeys: List[TxcVehicleJourney] = []
        debug_journey_codes = []
        for timetable in txc_xml:
            try:
                vehicle_journeys = timetable.get_vehicle_journeys()
            except NoElement:
                vehicle_journeys = []
            logger.debug(
                f"Timetable {timetable} has {len(vehicle_journeys)} vehicle journeys"
            )
            for vehicle_journey in vehicle_journeys:
                try:
                    operational = vehicle_journey.get_element("Operational")
                    ticket_machine = operational.get_element("TicketMachine")
                    journey_code = ticket_machine.get_element("JourneyCode").text
                    debug_journey_codes.append(journey_code)
                except (NoElement, TooManyElements):
                    continue
                if journey_code == vehicle_journey_ref:
                    logger.debug(
                        f"Found TicketMachine/JourneyCode {journey_code} in timetable "
                        f"{timetable.get_file_name()}"
                    )
                    matching_journeys.append(
                        TxcVehicleJourney(vehicle_journey, timetable)
                    )

        logger.info(
            f"Filtering by JourneyCode gave {len(vehicle_journeys)} matching journeys"
        )
        logger.debug(
            f"In {len(txc_xml)} timetables, found JourneyCode's: {debug_journey_codes}"
        )

        if len(matching_journeys) == 0:
            result.add_error(
                ErrorCategory.GENERAL,
                f"No vehicle journeys found with JourneyCode '{vehicle_journey_ref}'",
            )

        return matching_journeys

    def get_operating_profile_for_journey(
        self, vj: TxcVehicleJourney
    ) -> Optional[TransXChangeElement]:
        try:
            operating_profile = vj.vehicle_journey.get_element("OperatingProfile")
        except NoElement:
            services = vj.txc_xml.get_services()
            if len(services) == 0:
                return None
            operating_profile = services[0].get_element("OperatingProfile")
        except TooManyElements:
            return None
        return operating_profile

    def filter_by_operating_profile(
        self,
        activity_date,
        vehicle_journeys: List[TxcVehicleJourney],
        result: ValidationResult,
    ) -> bool:
        """Filter list of vehicle journeys down to those whose OperatingProfile applies
        to the VehiclActivity date. The OperatingProfile may be defined globally for
        the entire Service or individually for each VehicleJourney. Returns the list
        in place with inapplicable vehicle journeys removed.
        NOTE: Bank Holidays not yet supported
        """
        for vj in reversed(vehicle_journeys):
            operating_profile: TransXChangeElement = (
                self.get_operating_profile_for_journey(vj)
            )
            if operating_profile is None:
                logger.debug(
                    "Ignoring VehicleJourney with no operating profile: "
                    f"{vj.vehicle_journey}"
                )
                vehicle_journeys.remove(vj)
                continue
            holidays_only = operating_profile.find_anywhere("HolidaysOnly")
            if len(holidays_only) > 0:
                logger.info("Ignoring OperatingProfile with HolidaysOnly")
                vehicle_journeys.remove(vj)
                continue
            day_of_week = DayOfWeek.from_weekday_int(activity_date.weekday())
            profile_days_of_week = operating_profile.find_anywhere("DaysOfWeek")
            if len(profile_days_of_week) == 0:
                logger.info("Ignoring OperatingProfile with no DaysOfWeek")
                vehicle_journeys.remove(vj)
                continue
            specified_days = []
            for day in DayOfWeek:
                if profile_days_of_week[0].get_element_or_none(day.value) is not None:
                    specified_days.append(day)
            if day_of_week not in specified_days:
                logger.debug(
                    "Ignoring VehicleJourney with operating profile inapplicable to "
                    f"{day_of_week}"
                )
                vehicle_journeys.remove(vj)
        logger.info(
            f"Filtering by OperatingProfile left {len(vehicle_journeys)} matching "
            "journeys"
        )

        if len(vehicle_journeys) == 0:
            result.add_error(
                ErrorCategory.GENERAL,
                "No vehicle journeys found with OperatingProfile applicable to "
                "VehicleActivity date",
            )
            return False

        return True

    def filter_by_revision_number(
        self, vehicle_journeys: List[TxcVehicleJourney], result: ValidationResult
    ):
        """Filter list of vehicle journeys by revision number of the including
        timetable. Only return vehicle journeys pertaining to the file with the highest
        revision number. If more than one file has the highest revision number, return
        journeys pertaining to all those files. Returns the list in place with journeys
        from lower revision files removed.
        """
        highest_revision_number = -1
        for vj in reversed(vehicle_journeys):
            try:
                revision_number = int(vj.txc_xml.get_revision_number())
            except (ValueError, XMLAttributeError):
                vehicle_journeys.remove(vj)
                continue
            if revision_number > highest_revision_number:
                highest_revision_number = revision_number

        for vj in reversed(vehicle_journeys):
            revision_number = int(vj.txc_xml.get_revision_number())
            if revision_number < highest_revision_number:
                vehicle_journeys.remove(vj)

        if len(vehicle_journeys) == 0:
            result.add_error(
                ErrorCategory.GENERAL,
                "No RevisionNumber found in matching vehicle journeys",
            )
            return False

        if len(vehicle_journeys) > 1:
            result.add_error(
                ErrorCategory.GENERAL,
                "Found more than one matching vehicle journey in timetables",
            )
            return False

        return True

    def record_journey_match(
        self, result: ValidationResult, vehicle_journey_ref: str, vj: TxcVehicleJourney
    ):
        result.set_txc_value(SirivmField.DATED_VEHICLE_JOURNEY_REF, vehicle_journey_ref)
        result.set_matches(SirivmField.DATED_VEHICLE_JOURNEY_REF)
        result.set_journey_matched()

        result.set_misc_value(MiscFieldPPC.TXC_FILENAME, vj.txc_xml.get_file_name())
        result.set_misc_value(
            MiscFieldPPC.TXC_FILE_REVISION, vj.txc_xml.get_revision_number()
        )
        departure_time = vj.vehicle_journey.get_element_or_none("DepartureTime")
        if departure_time:
            result.set_misc_value(MiscFieldPPC.TXC_DEPARTURE_TIME, departure_time.text)

        logger.info(
            f"MATCHED {vj.txc_xml.get_file_name()} "
            f"revision {vj.txc_xml.get_revision_number()}"
        )

    def match_vehicle_activity_to_vehicle_journey(
        self,
        activity: VehicleActivity,
        result: ValidationResult,
    ) -> Optional[TxcVehicleJourney]:
        """Match a SRI-VM VehicleActivity to a TXC VehicleJourney."""
        mvj = activity.monitored_vehicle_journey

        if not self.check_operator_and_line_present(activity, result):
            return None

        matching_txc_file_attrs = self.get_txc_file_metadata(
            noc=mvj.operator_ref, line_name=mvj.line_ref, result=result
        )
        if not matching_txc_file_attrs:
            return None

        if not self.check_same_dataset(matching_txc_file_attrs, mvj, result):
            return None

        txc_xml = self.get_corresponding_timetable_xml_files(matching_txc_file_attrs)

        if not self.filter_by_operating_period(
            activity.recorded_at_time.date(), txc_xml, result
        ):
            return None

        if (vehicle_journey_ref := self.get_vehicle_journey_ref(mvj)) is None:
            result.add_error(
                ErrorCategory.GENERAL,
                "DatedVehicleJourneyRef missing in SIRI-VM VehicleActivity",
            )
            return None

        vehicle_journeys = self.filter_by_journey_code(
            txc_xml, vehicle_journey_ref, result
        )
        if not vehicle_journeys:
            return None

        if not self.filter_by_operating_profile(
            activity.recorded_at_time.date(), vehicle_journeys, result
        ):
            return None

        if not self.filter_by_revision_number(vehicle_journeys, result):
            return None

        # If we get to this point, we've matched the SIRI-VM MonitoredVehicleJourney
        # to exactly one TXC VehicleJourney. Update result to record a match.
        txc_vehicle_journey = vehicle_journeys[0]
        self.record_journey_match(result, vehicle_journey_ref, txc_vehicle_journey)
        return txc_vehicle_journey
