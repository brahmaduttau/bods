import logging
import zipfile

from django.http import JsonResponse
from lxml import etree
from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.parsers import FileUploadParser
from rest_framework.views import APIView

from ..models import FaresValidation
from ..serializers import FaresSerializer

logger = logging.getLogger(__name__)
type_of_observation = "Simple fares validation failure"
category = ""  # Itr2 To be extratced from the xml path
schema_path = (
    "transit_odp/fares_validator/xml_schema/netex_dataObjectRequest_service.xsd"
)


class FaresXmlValidator(APIView):
    parser_classes = [FileUploadParser]

    def get(self, request, pk1, pk2):
        validations = FaresValidation.objects.filter(
            dataset_id=pk2, organisation_id=pk1
        )
        serializer = FaresSerializer(validations, many=True)
        return JsonResponse({"errors": serializer.data}, safe=False)

    def post(self, request, pk1, pk2, format=None):
        if "file" not in request.data:
            raise ParseError("Empty content")
        file_obj = request.data["file"]
        etree_obj_list = {}

        with open(
            schema_path,
            "r",
        ) as f:
            schema = f.read()

        if schema is not None:
            lxml_schema = self.get_lxml_schema(schema)

        file_name = file_obj.name
        if file_name.endswith(".xml"):
            xmlschema_doc = etree.parse(file_obj)
            etree_obj_list[file_name] = xmlschema_doc
        elif file_name.endswith(".zip"):
            with zipfile.ZipFile(file_obj, "r") as zout:
                filenames = [name for name in zout.namelist() if name.endswith("xml")]
                for file_name in filenames:
                    if not file_name.startswith("__"):
                        with zout.open(file_name) as xmlout:
                            xmlschema_doc = etree.parse(xmlout)
                            etree_obj_list[file_name] = xmlschema_doc

        for xmlschema_doc in etree_obj_list:
            try:
                lxml_schema.assertValid(etree_obj_list[xmlschema_doc])
            except etree.DocumentInvalid:
                for error in lxml_schema.error_log:
                    fares_validator_model_object = FaresValidation(
                        dataset_id=pk2,
                        organisation_id=pk1,
                        file_name=xmlschema_doc,
                        error_line_no=error.line,
                        error=error.message,
                        type_of_observation=type_of_observation,
                        category=category,
                    )
                    fares_validator_model_object.save()

        validations = FaresValidation.objects.filter(dataset_id=pk2)
        serializer = FaresSerializer(validations, many=True)
        return JsonResponse({"errors": serializer.data}, status=status.HTTP_201_CREATED)

    def get_lxml_schema(self, schema):
        """Creates an lxml XMLSchema object from a file, file path or url."""

        if schema is None:
            return

        if not isinstance(schema, etree.XMLSchema):
            logger.info(f"[XML] => Parsing {schema}.")
            root = etree.parse(schema_path)
            schema = etree.XMLSchema(root)
        return schema
