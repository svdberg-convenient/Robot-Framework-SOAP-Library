import os
import logging.config
import warnings
import base64
from .config import DICT_CONFIG
from requests import Session
from requests.auth import HTTPBasicAuth
from zeep import Client
from zeep.cache import SqliteCache
from zeep.transports import Transport
from zeep.wsdl.utils import etree
from robot.api import logger
from robot.api.deco import keyword
from urllib3.exceptions import InsecureRequestWarning
from .version import VERSION

logging.config.dictConfig(DICT_CONFIG)
# hide unnecessary warnings
warnings.simplefilter("ignore", InsecureRequestWarning)
logging.getLogger("urllib3").setLevel(logging.WARNING)

DEFAULT_HEADERS = {'Content-Type': 'text/xml; charset=utf-8'}


class SoapLibrary:
    ROBOT_LIBRARY_SCOPE = 'TEST SUITE'
    ROBOT_LIBRARY_VERSION = VERSION

    def __init__(self):
        self.client = None
        self.url = None
        self.response_obj = None

    @keyword("Create SOAP Client")
    def create_soap_client(self, url, ssl_verify=True, client_cert=None, auth=None, use_binding_address=False):
        """
        Loads a WSDL from the given ``url`` and creates a Zeep client.
        List all Available operations/methods with INFO log level.

        By default, server TLS certificate is validated. You can disable this behavior by setting ``ssl_verify``
        to ``False`` (not recommended!). If your host uses a self-signed certificate, you can also pass the path of the
        CA_BUNDLE to ``sll_verify``. Accepted are only X.509 ASCII files (file extension .pem, sometimes .crt).
        If you have two different files for root and intermediate certificate, you must combine them manually into one.

        If your host requires client certificate based authentication, you can pass the
        path to your client certificate to the ``client_cert`` argument.

        For HTTP Basic Authentication, you can pass the list with username and password
        to the ``auth`` parameter.

        If you want to use the binding address in the requests, you need to pass use_binding_address=True in
        the argument.

        *Example:*
        | Create SOAP Client | http://endpoint.com?wsdl |
        | Create SOAP Client | https://endpoint.com?wsdl | ssl_verify=True |
        | Create SOAP Client | https://endpoint.com?wsdl | use_binding_address=True |
        | Create SOAP Client | https://endpoint.com?wsdl | client_cert=${CURDIR}${/}mycert.pem |
        | ${auth} | Create List | username | password |
        | Create SOAP Client | https://endpoint.com?wsdl | auth=${auth} |
        """
        self.url = url
        session = Session()
        session.verify = ssl_verify
        session.cert = client_cert
        session.auth = HTTPBasicAuth(*auth) if auth else None
        self.client = Client(self.url, transport=Transport(session=session, cache=SqliteCache()))
        logger.info('Connected to: %s' % self.client.wsdl.location)
        info = self.client.service.__dict__
        operations = info["_operations"]
        logger.info('Available operations: %s' % list(operations))
        if use_binding_address:
            self.url = self.client.service._binding_options['address']

    @keyword("Call SOAP Method With XML")
    def call_soap_method_xml(self, xml, headers=DEFAULT_HEADERS, status=None):
        """
        Send an XML file as a request to the SOAP client. The path to the Request XML file is required as argument,
        the SOAP method is inside the XML file.

        By default, this keyword fails if a status code different from 200 is returned as response,
        this behavior can be modified using the argument status=anything.

        *Input Arguments:*
        | *Name* | *Description* |
        | xml | file path to xml file |
        | headers | dictionary with request headers. Default ``{'Content-Type': 'text/xml; charset=utf-8'}`` |
        | status | optional string: anything |

        *Example:*
        | ${response}= | Call SOAP Method With XML | ${CURDIR}${/}Request.xml |
        | ${response}= | Call SOAP Method With XML | ${CURDIR}${/}Request_status_500.xml | status=anything |
        """
        raw_text_xml = self._convert_xml_to_raw_text(xml)
        xml_obj = etree.fromstring(raw_text_xml)
        response = self.client.transport.post_xml(address=self.url, envelope=xml_obj, headers=headers)
        self._save_response_object(response)
        etree_response = self._parse_from_unicode(response.text)
        self._check_and_print_response(response, etree_response, status)
        return etree_response

    @keyword("Get Data From XML By Tag")
    def get_data_from_xml_tag(self, xml, tag, index=1):
        """
        Gets data from XML using a given tag.
        If the tag returns zero or more than one result, it will show a warning. The xml argument must be an
        etree object, can be used with the return of the keyword `Call SOAP Method With XML`.

        Returns the string representation of the value.

        *Input Arguments:*
        | *Name* | *Description* |
        | xml | xml etree object |
        | tag | tag to get value from |
        | index | tag index if there are multiple tags with the same name, starting at 1. Default is set to 1 |

        *Examples:*
        | ${response}= | Call SOAP Method With XML | ${CURDIR}${/}Request.xml |
        | ${value}= | Get Data From XML By Tag | ${response} | SomeTag |
        | ${value}= | Get Data From XML By Tag | ${response} | SomeTag | index=9 |
        """
        new_index = index - 1
        xpath = self._parse_xpath(tag)
        data_list = xml.xpath(xpath)
        if isinstance(data_list, (float, int)):
            return int(data_list)
        if len(data_list) == 0:
            logger.warn('The search "%s" did not return any result! Please confirm the tag!' % xpath)
        elif len(data_list) > 1:
            logger.debug('The tag you entered found %s items, returning the text in the index '
                         'number %s, if you want a different index inform the argument index=N' % (len(data_list), index))
        return data_list[new_index].text

    @keyword("Edit XML Request")
    def edit_xml(self, xml_file_path, new_values_dict, edited_request_name, repeated_tags='All'):
        """
        Changes a field on the given XML to a new given value, the values must be in a dictionary xml_filepath must be
        a "template" of the request to the webservice. new_values_dict must be a dictionary with the keys
        and values to change. request_name will be the name of the new XMl file generated with the changed request.

        If there is a tag that appears more than once, all occurrences will be replaced by the new value by default.
        If you want to change a specific tag, inform the occurrence number in the repeated_tags argument.

        Returns the file path of the new Request file.

        *Input Arguments:*
        | *Name* | *Description* |
        | xml_file_path | file path to xml file |
        | new_values_dict | dictionary with tags as keys and tag value as value |
        | edited_request_name |  name of the new XMl file generated with the changed request |
        | repeated_tags |  Occurrence number of the repeated tag to change value |

        *Example*:
        | ${dict}= | Create Dictionary | tag_name1=SomeText | tag_name2=OtherText |
        | ${xml_edited}= | Edit XML Request | request_filepath | ${dict} | New_Request |
        | ${xml_edited}= | Edit XML Request | request_filepath | ${dict} | New_Request | repeated_tags=0 |
        """
        string_xml = self._convert_xml_to_raw_text(xml_file_path)
        xml = self._convert_string_to_xml(string_xml)
        if not isinstance(new_values_dict, dict):
            raise Exception("new_values_dict argument must be a dictionary")
        for key, value in new_values_dict.items():
            if len(xml.xpath(self._replace_xpath_by_local_name(key))) == 0:
                logger.warn('Tag "%s" not found' % key)
                continue
            xml_xpath = self._replace_xpath_by_local_name(key)
            count = int(xml.xpath(("count(%s)" % xml_xpath)))
            logger.debug("Found %s tags with xpath %s" % (str(count), xml_xpath))
            if repeated_tags == 'All' or count < 2:
                for i in range(count):
                    xml.xpath(xml_xpath)[i].text = value
            else:
                xml.xpath(xml_xpath)[int(repeated_tags)].text = value
        # Create new file with replaced request
        new_file_path = self._save_to_file(os.path.dirname(xml_file_path), edited_request_name, etree.tostring(xml))
        return new_file_path

    @keyword("Save XML To File")
    def save_xml_to_file(self, etree_xml, save_folder, file_name):
        """
        Save the webservice response as an XML file.

        Returns the file path of the newly created xml file.

        *Input Arguments:*
        | *Name* | *Description* |
        | etree_xml | etree object of the xml |
        | save_folder | directory to save the new file |
        | file_name | name of the new xml file without .xml |

        *Example*:
        | ${response}= | Call SOAP Method With XML | ${CURDIR}${/}Request.xml |
        | ${response_file}= | Save XML To File | ${response} | ${CURDIR} | response_file_name |
        """
        new_file_path = self._save_to_file(save_folder, file_name, etree.tostring(etree_xml, pretty_print=True))
        return new_file_path

    @keyword("Convert XML Response to Dictionary")
    def convert_response_dict(self, xml_etree):
        """
        Convert the webservice response into a dictionary.

        *Input Arguments:*
        | *Name* | *Description* |
        | xml_etree | etree object of the xml to convert to dictionary |

        *Example:*
        | ${response}= | Call SOAP Method With XML | ${CURDIR}${/}Request.xml |
        | ${dict_response}= | Convert XML Response to Dictionary | ${response} |
        """
        # Thanks to Jamie Murphy for this code: https://gist.github.com/jacobian/795571
        result = {}
        for element in xml_etree.iterchildren():
            # Remove namespace prefix
            key = element.tag.split('}')[1] if '}' in element.tag else element.tag
            # Process element as tree element if the inner XML contains non-whitespace content
            if element.text and element.text.strip():
                value = element.text
            else:
                value = self.convert_response_dict(element)
            if key in result:
                if type(result[key]) is list:
                    result[key].append(value)
                else:
                    tempvalue = result[key].copy()
                    result[key] = [tempvalue, value]
            else:
                result[key] = value
        return result

    @keyword("Call SOAP Method")
    def call_soap_method(self, name, *args, status=None):
        """
        If the webservice have simple SOAP operation/method with few arguments, you can call the method with the given
        `name` and `args`.

        The first argument of the keyword  ``name``  is the operation name of the ``SOAP operation/method``
        [https://www.soapui.org/soap-and-wsdl/operations-and-requests.html|More information here]

        By default, this keyword fails if a status code different from 200 is returned as response,
        this behavior can be modified using the argument status=anything.

        *Input Arguments:*
        | *Name* | *Description* |
        | name | Name of the SOAP operation/method |
        | args | List of request entries |
        | status | if set as anything, return the error as a string |

        Note, this keyword uses the most basic method of sending a request, through zeep that creates the xml based
        on the wsdl definition. So this keyword does not store the response object, and therefore it is not possible
        to use the keyword `Get Last Response Object` after this one.

        *Example:*
        | ${response}= | Call SOAP Method | operation_name | arg1 | arg2 |
        | ${response}= | Call SOAP Method | operation_name | arg1 | arg2 | status=anything |
        """
        method = getattr(self.client.service, name)
        if status is None:
            response = method(*args)
        else:
            try:
                response = method(*args)
            except Exception as e:
                response = str(e)
        return response

    @keyword("Decode Base64")
    def decode_base64(self, response):
        """
        Decodes texts that are base64 encoded.

        Returns the decoded response.

        *Input Arguments:*
        | *Name* | *Description* |
        | response | Response of the webservice coded in base64 |

        *Example:*
        | ${response}= | Call SOAP Method With XML | ${CURDIR}${/}Request.xml |
        | ${response_decoded}= | Decode Base64 | ${response} |
        """
        response_decode = base64.b64decode(response)
        return response_decode.decode('utf-8', 'ignore')

    @keyword("Call SOAP Method With String XML")
    def call_soap_method_string_xml(self, string_xml, headers=DEFAULT_HEADERS, status=None):
        """
        Send a string representation of XML as a request to the SOAP client.
        The SOAP method is inside the XML string.

        By default, this keyword fails if a status code different from 200 is returned as response,
        this behavior can be modified using the argument status=anything.

        *Input Arguments:*
        | *Name* | *Description* |
        | string_xml | string representation of XML |
        | headers | dictionary with request headers. Default ``{'Content-Type': 'text/xml; charset=utf-8'}`` |
        | status | optional string: anything |

        *Example:*
        | ${response}= | Call SOAP Method With String XML | "<sample><Id>1</Id></sample>" |
        | ${response}= | Call SOAP Method With String XML | "<sample><Id>error</Id></sample>" | status=anything |
        """
        xml_obj = etree.fromstring(string_xml)
        response = self.client.transport.post_xml(address=self.url, envelope=xml_obj, headers=headers)
        self._save_response_object(response)
        etree_response = self._parse_from_unicode(response.text)
        self._check_and_print_response(response, etree_response, status)
        return etree_response

    @keyword("Get Last Response Object")
    def get_last_response_object(self):
        """
        Gets the response object from the last request made. With the object in a variable, you can use the
        dot operator to get all the attributes of the response.

        Response object attributes:
        | apparent_encoding |
        | close |
        | connection |
        | content |
        | cookies |
        | elapsed |
        | encoding |
        | headers |
        | history |
        | is_permanent_redirect |
        | is_redirect |
        | iter_content |
        | iter_lines |
        | json |
        | links |
        | next |
        | ok |
        | raise_for_status |
        | raw |
        | reason |
        | request |
        | status_code |
        | text |
        | url |

        Note, this keyword only works after the execution of `Call SOAP Method With XML` or
        `Call SOAP Method With String XML`.

        *Example:*
        | ${response}= | Call SOAP Method With XML | ${CURDIR}${/}Request.xml |
        | ${response_object}= | Get Last Response Object |
        | ${response_header}= | Set Variable | ${response_object.headers} |
        | ${response_status}= | Set Variable | ${response_object.status_code} |
        """
        return self.response_obj

    @staticmethod
    def _convert_xml_to_raw_text(xml_file_path):
        """
        Converts a xml file into a string.

        :param xml_file_path: xml file path.
        :return: string with xml content.
        """
        file_content = open(xml_file_path, 'r')
        xml = ''
        for line in file_content:
            xml += line
        file_content.close()
        return xml

    @staticmethod
    def _parse_from_unicode(unicode_str):
        """
        Parses a unicode string.
        
        :param unicode_str: unicode string.
        :return: parsed string.
        """
        utf8_parser = etree.XMLParser(encoding='utf-8')
        string_utf8 = unicode_str.encode('utf-8')
        return etree.fromstring(string_utf8, parser=utf8_parser)

    def _parse_xpath(self, tags):
        """
        Parses a single xpath or a list of xml tags.

        :param tags: string for a single xml tag or list for multiple xml tags.
        :return: parsed xpath.
        """
        xpath = ''
        if isinstance(tags, list):
            for el in tags:
                xpath += self._replace_xpath_by_local_name(el)
        else:
            xpath += self._replace_xpath_by_local_name(tags)
        return xpath

    def _check_and_print_response(self, response, etree_response, status):
        """
        Check if the response is 200 when the status is None and pretty print in the robot log.

        :param response: response object.
        :param etree_response: response object in etree format.
        :param status: if is not None, then don´t raise error.
        """
        logger.debug('URL: %s' % response.url)
        logger.debug(etree.tostring(etree_response, pretty_print=True, encoding='unicode'))
        if status is None and response.status_code != 200:
            raise AssertionError('Request Error! Status Code: %s! Reason: %s' % (response.status_code, response.reason))
        self._print_request_info(etree_response)

    def _save_response_object(self, response):
        """
        Log the response status code in Robot Framework log and save the response object
        for use in the keyword 'Get Last Response Object'

        :param response, zeep response object.
        """
        logger.info('Status code: %s' % response.status_code)
        self.response_obj = response

    @staticmethod
    def _convert_string_to_xml(xml_string):
        """
        Converts a given string to xml object using etree.
        
        :param xml_string: string with xml content.
        :return: xml object.
        """
        return etree.fromstring(xml_string)

    @staticmethod
    def _replace_xpath_by_local_name(xpath_tag):
        """
        Replaces the given xpath_tag in a xpath using name() function.
        Returns the replaced xpath.

        :param xpath_tag: tag to replace with in xpath.
        :return: replaced xpath tag.
        """
        local_name_xpath = "//*[name()='%s']"
        return local_name_xpath % xpath_tag

    @staticmethod
    def _save_to_file(save_folder, file_name, text):
        """
        Saves text into a new file.

        :param save_folder: folder to save the new xml file.
        :param file_name: name of the new file.
        :param text: file text.
        :return new file path.
        """
        new_file_name = "%s.xml" % file_name
        new_file_path = os.path.join(save_folder, new_file_name)
        request_file = open(new_file_path, 'wb')
        request_file.write(text)
        request_file.close()
        return new_file_path

    @staticmethod
    def _print_request_info(etree_response):
        """
        Pretty print for robot framework log.
        """
        log_header_response_from_ws = '<font size="3"><b>Response from webservice:</b></font> '
        logger.info(log_header_response_from_ws, html=True)
        logger.info(etree.tostring(etree_response, pretty_print=True, encoding='unicode'))
