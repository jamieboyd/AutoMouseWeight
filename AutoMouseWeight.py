#! /usr/bin/python
#-*-coding: utf-8 -*-

"""
AutoMouseWeight program to automatically weigh RFID tagged individuals as they cross an
HX711-based scale with an Innovations Design RFID Tag reader installed
Designed for mice, but it could be used for anything that can move and carry an RFID tag
Last Modified:
2018/05/11 by Jamie Boyd - moved mose constants for settings into a JSON file
2018/03/07 by Jamie Boyd - cleaned up a bit, added some comments
"""
import RFIDTagReader
from RFIDTagReader import TagReader
from Scale import Scale
import RPi.GPIO as GPIO
from array import array
from time import time, sleep
from datetime import date, datetime, timedelta
import json

kTIMEOUTSECS= 0.05 #time to sleep in each pass through loop while witing for RFID reader

"""
readibility constants for where data is saved. Work is in progress for sending data
to a remote server for analysis and display on a web page. For now, always
set kSAVE_DATA to kSAVE_DATA_LOCAL
"""
kSAVE_DATA_LOCAL =1
kSAVE_DATA_REMOTE =2


def main():
    """
    Read in settings from AMW_config.jsn. If we don't find the file, make it.
    Note that we save the file with new line as a separator, but can't load it with a non-standard separator,
    so we replace new lines with  commas, he default separator character
    
    """
    try:
        with open ('AMW_config.jsn', 'r') as fp:
            data = fp.read()
            data = data.replace('\n', ',')
            configDict = json.loads(data)
            fp.close()
            # Constants for saving data
            # cage name, to tell data from different cages 
            kCAGE_NAME = configDict.get ('Cage Name')
            # path where data from each day will be saved
            kCAGE_PATH = configDict.get ('Data Path')
            # rollover time, 0 to start the file for each day at 12 midnight. Could set to 7 to synch files to mouse day/night cycle
            kDAYSTARTHOUR = configDict.get ('Day Start Hour')
            # size of array used for threaded reading from load cell amplifier
            kTHREADARRAYSIZE = configDict.get ('Thread Array Size')
            # cuttoff weight where we stop the thread from reading when a mouse steps away
            kMINWEIGHT = configDict.get ('Minimum Weight')
            # GPIO pin numbers and scaling for HX711, adjust as required for individual setup
            kDATA_PIN= configDict.get ('GPIO Data Pin')
            kCLOCK_PIN=configDict.get ('GPIO Clock Pin')
            kGRAMS_PER_UNIT=configDict.get ('Grams Per Unit')
            # RFID Reader. Note that code as written only works with ID tag readers not RDM readers because of reliance on Tag-In-Range Pin
            kSERIAL_PORT = configDict.get ('Serial Port')
            kTIR_PIN = configDict.get ('GPIO Tag In Range Pin')
            #whether data is saved locally 1 or, not yet supported, sent to a server 2, or both, 3
            kSAVE_DATA = configDict.get ('Data Save Options')
            # a dictionary of ID Tags and cutoff weights, as when monitoring animal weights over time
            kHAS_CUTOFFS = configDict.get ('Has Cutoffs')
            if kHAS_CUTOFFS:
                kCUT_OFF_DICT = configDict.get ('Cutoff Dict')
            else:
                kCUT_OFF_DICT =None
            # can call get day weights code and email weights, needs extra options
            kEMAIL_WEIGHTS = configDict.get ('Email Weights')
            if kEMAIL_WEIGHTS:
                kEMAIL_DICT = configDict.get ('Email Dict')
            else:
                kEMAIL_DICT = None
    except (TypeError, IOError, ValueError) as e:
            #we will make a file if we didn't find it, or if it was incomplete
            print ('Unable to load configuration data from AMW_config.jsn, let\'s make a new AMW_config.jsn.\n')
            jsonDict = {}
            kCAGE_NAME = input('Enter the cage name, used to distinguish data from different cages:')
            kCAGE_PATH = input ('Enter the path where data from each day will be saved:')
            kDAYSTARTHOUR = int (input ('Enter the rollover hour, in 24 hour format, when a new data file is started:'))
            kTHREADARRAYSIZE = int (input ('Enter size of array used for threaded reading from Load Cell:'))
            kMINWEIGHT = float (input ('Enter cutoff weight where we stop the thread from reading:'))
            kDATA_PIN=  int (input ('Enter number of GPIO pin connected to data pin on load cell:'))
            kCLOCK_PIN = int (input ('Enter number of GPIO pin connected to clock pin on load cell:'))
            kGRAMS_PER_UNIT = float (input('Enter the scaling of the load cell, in grams per A/D unit:'))
            kSERIAL_PORT = input ('Enter the name of serial port used for tag reader,e.g. serial0 or ttyAMA0:')
            kTIR_PIN = int (input ('Enter number of the GPIO pin connected to the Tag-In-Range pin on the RFID reader:'))
            kSAVE_DATA = int (input ('To save data locally, enter 1; to send data to a server, not yet supported, enter 2:'))
            tempInput = input ('Track weights against existing cutoffs(Y or N):')
            kHAS_CUTOFFS = bool(tempInput [0] == 'y' or tempInput [0] == 'Y')
            if kHAS_CUTOFFS:
                kCUT_OFF_DICT = {}
                while True:
                    tempInput = input ('Enter a Tag ID and cuttoff weight, separated by a comma, or return to end entry:')
                    if tempInput == "":
                        break
                    entryList = tempInput.split(',')
                    try:
                        kCUT_OFF_DICT.update ({entryList[0] : float (entryList[1])})
                    except Exception as e:
                        print ('bad data entered', str (e))
            else:
                kCUT_OFF_DICT=None
            jsonDict.update ({'Has Cutoffs':kHAS_CUTOFFS, 'Cutoff Dict': kCUT_OFF_DICT})
            tempInput = input ('Email weights every day ? (Y or N):')
            kEMAIL_WEIGHTS = bool(tempInput [0] == 'y' or tempInput [0] == 'Y')
            if kEMAIL_WEIGHTS:
                kEMAIL_DICT = {}
                kFROMADDRESS = input ('Enter the account used to send the email with  weight data:')
                kPASSWORD = input ('Enter the password for the email account used to send the mail:')
                kSERVER = input ('Enter the name of the email server and port number, e.g., smtp.gmail.com:87, with separating colon:')
                kRECIPIENTS = tuple (input('Enter comma-separated list of email addresses to get the daily weight email:').split(','))
                kEMAIL_DICT.update ({'Email From Address':kFROMADDRESS, 'Email Recipients':kRECIPIENTS})
                kEMAIL_DICT.update ({'Email Password':kPASSWORD, 'Email Server': kSERVER})
            else:
                kEMAIL_DICT = None
            jsonDict.update ({'Email Weights' : kEMAIL_WEIGHTS, 'Email Dict' : kEMAIL_DICT})
            # add info to a dictionay we will write to file
            jsonDict.update ({'Cage Name':kCAGE_NAME, 'Data Path':kCAGE_PATH, 'Day Start Hour':kDAYSTARTHOUR, 'Thread Array Size':kTHREADARRAYSIZE})
            jsonDict.update ({'Minimum Weight':kMINWEIGHT, 'GPIO Data Pin': kDATA_PIN, 'GPIO Clock Pin':kCLOCK_PIN})
            jsonDict.update ({'GPIO Tag In Range Pin':kTIR_PIN, 'Grams Per Unit':kGRAMS_PER_UNIT, 'Serial Port':kSERIAL_PORT})
            jsonDict.update ({'Data Save Options':kSAVE_DATA, 'Email Weights':kEMAIL_WEIGHTS})
            with open ('AMW_config.jsn', 'w') as fp:
                fp.write (json.dumps (jsonDict, sort_keys = True, separators=('\r\n', ':')))
    """
    Initialize the scale from variables listed above and do an initial taring
    of the scale with 10 reads. Because pins are only accessed from C++, do not call
    Python GPIO.setup for the dataPin and the clockPin
    """
    scale = Scale (kDATA_PIN, kCLOCK_PIN, kGRAMS_PER_UNIT, kTHREADARRAYSIZE)
    scale.weighOnce ()
    scale.tare(10, True)
    """
    Setup tag reader and GPIO for TIR pin, with tagReaderCallback installed as
    an event callback when pin changes either from low-to-high, or from high-to-low.
    """
    tagReader = TagReader('/dev/' + kSERIAL_PORT, doChecksum = False, timeOutSecs = 0.05, kind='ID')
    tagReader.installCallBack (kTIR_PIN)
    """
    A new binary data file is opened for each day, with a name containing the 
    current date, so open a file to start with
    """
    now = datetime.fromtimestamp (int (time()))
    startDay = datetime (now.year, now.month,now.day, kDAYSTARTHOUR,0,0)
    if startDay > now: # it's still "yesterday" according to kDAYSTARTHOUR definition of when a day starts
        startDay = startDay - timedelta (hours=24)
    startSecs = startDay.timestamp() # used to report time of an entry through the weighing tube
    nextDay = startDay + timedelta (hours=24)
    filename = kCAGE_PATH + kCAGE_NAME + '_' + str (startDay.year) + '_' + '{:02}'.format(startDay.month)+ '_' + '{:02}'.format (startDay.day)
    if kSAVE_DATA & kSAVE_DATA_LOCAL:
        print ('opening file name = ' + filename)
        outFile=open (filename, 'ab')
        from OneDayWeights import get_day_weights
    """
    Weight data is written to the file as grams, in 32 bit floating point format. Each run of data is
    prefaced by metadata from a 32 bit floating point metaData array of size 2. The first point contains
    the last 6 digits of the RFID code, as a negative value to make it easy for analysis code to find the
    start of each run. The second point contains the time in seconds since the start of the day.
    Both data items have been selected to fit into a 32 bit float.
    """
    metaData = array ('f', [0,0])
    
    while True:
        try:
            """
            Loop with a brief sleep, waiting for a tag to be read
            or a new day to start, in which case a new data file is made
            """
            while RFIDTagReader.globalTag==0:
                if datetime.fromtimestamp (int (time())) > nextDay:
                    if kSAVE_DATA & kSAVE_DATA_LOCAL:
                        outFile.close()
                        print ('save data date =', startDay.year, startDay.month, startDay.day)
                        try:
                            get_day_weights (kCAGE_PATH, kCAGE_NAME, startDay.year, startDay.month, startDay.day, kCAGE_PATH, False, kEMAIL_DICT, kCUT_OFF_DICT)
                        except Exception as e:
                            print ('Error getting weights for today:' + str (e)) 
                    startDay = nextDay
                    nextDay = startDay + timedelta (hours=24)
                    startSecs =startDay.timestamp()
                    filename = kCAGE_PATH + kCAGE_NAME + '_' + str (startDay.year) + '_' + '{:02}'.format(startDay.month)  + '_' + '{:02}'.format (startDay.day)
                    if kSAVE_DATA & kSAVE_DATA_LOCAL:
                        outFile=open (filename, 'ab')
                        print ('opening file name = ' + filename)
                else:
                    sleep (kTIMEOUTSECS)
            """
            A Tag has been read. Fill the metaData array and tell the C++ thread to start
            recording weights
            """
            thisTag = RFIDTagReader.globalTag
            startTime =time()
            print ('mouse = ', thisTag)
            #scale.turnOn()
            metaData [0]= -(thisTag%1000000)
            metaData[1]=startTime-startSecs
            scale.threadStart (scale.arraySize)
            nReads = scale.threadCheck()
            lastRead=0
            """
            Keep reading weights into the array until a new mouse is read by 
            the RFID reader, or the last read weight drops below 2 grams, or
            the array is full, then stop the thread print the metaData array
            and the read weights from the thread array to the file
            """
            while ((RFIDTagReader.globalTag == thisTag or (RFIDTagReader.globalTag == 0 and scale.threadArray [nReads-1] > kMINWEIGHT)) and nReads < scale.arraySize):
                if nReads > lastRead:
                    print (nReads, scale.threadArray [nReads-1])
                    lastRead = nReads
                sleep (0.05)
                nReads = scale.threadCheck()
            nReads = scale.threadStop()
            if kSAVE_DATA & kSAVE_DATA_LOCAL:
                metaData.tofile (outFile)
                scale.threadArray[0:nReads-1].tofile(outFile)
            if kSAVE_DATA & kSAVE_DATA_REMOTE:
		# modify to send : Time:UNIX time stamp, RFID:FULL RFID Tag, CageID: id, array: weight array
                response = requests.post(kSERVER_URL, data={'tag': thisTag, 'cagename': kCAGE_NAME, 'datetime': int (startTime), 'array': str ((metaData + scale.threadArray[0:nReads-1]).tobytes(), 'latin_1')}).text
                if response != '\nSuccess\n':
                    print (reponse)
            #scale.turnOff()
        except KeyboardInterrupt:
            #scale.turnOn()
            event = scale.scaleRunner ('10:\tQuit AutoMouseWeight program\n')
            if event == 10:
                if kSAVE_DATA & kSAVE_DATA_LOCAL:
                    outFile.close()
                GPIO.cleanup()
                return
        except Exception as error:
            print("Closing file...")
            outFile.close()
            GPIO.cleanup()
            raise error


if __name__ == '__main__':
   main()
