#! /usr/bin/python
#-*-coding: utf-8 -*-
from AHF_TagReader import AHF_TagReader
from Scale import Scale
import RPi.GPIO as GPIO
from array import array
from time import time, sleep
from datetime import date, datetime, timedelta

# Constants for saving data
kCAGE_NAME = 'cage_0'   # cage name, to tell data from different cages 
kCAGE_PATH = '/home/pi/Documents/AutoMouseWeight_Data/' # path where data from each day will be saved

kDAYSTARTHOUR = 13 # 0 to start the file for each day at 12 midnight. Could set to 7 to synch files to mouse day/night cycle
kTIMEOUTSECS=0.05 #time to sleep in each pass through loop while witing for RFID reader
kTHREADARRAYSIZE = 200 # size of array used for threaded reading from load cell amplifier
# Global variables for RFID reader - need to be global so we can access reader easily from interrupt
tag =0
serialPort = '/dev/serial0'
tagReader = RFID_TagReader(serialPort, False)

"""
Threaded call back function on Tag-In-Range pin
Updates tag global variable whenever Tag-In-Range pin toggles
Setting tag to 0 means no tag is presently in range
"""
def tagReaderCallback (channel):
    global tag # the global indicates that it is the same variable declared above and also used by main loop
    if GPIO.input (channel) == GPIO.HIGH: # mouse just entered
        tag = tagReader.readTag ()
    else:  # mouse just left
        tag = 0


def main():

    """
    Variables for GPIO pin numbers and scaling, adjust as required for individual setup
    set initGPIO to be false only if using wiringPi library for other purposes
    and wiringPi GPIO initialization has already been done.
    """
    dataPin=17
    clockPin=27
    gmPerUnit=7.14e-05
    tirPin=22
    # save data locally and/or remotely
    saveData = kSAVE_DATA_LOCAL
    """
    Initialize the scale from variables listed above and do an initial taring
    of the scale with 5 reads. Because pins are accessed from C++, do not call
    Python GPIO.setup for the dataPin and the clockPin
    """
    scale = Scale (dataPin, clockPin, gmPerUnit)
    scale.turnOn()
    scale.threadSetArraySize (kTHREADARRAYSIZE)
    scale.tare(10, True)
    """
    Setup GPIO for TIR pin, with tagReaderCallback installed as
    an event callback when pin changes either from low-to-high, or from high-to-low.
    """
    GPIO.setmode (GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup (tirPin, GPIO.IN)
    GPIO.add_event_detect (tirPin, GPIO.BOTH)
    GPIO.add_event_callback (tirPin, tagReaderCallback)

    """
    A new binary data file is opened for each day, with a name containing the 
    current date, so open a file to start with
    """
    now = datetime.fromtimestamp (int (time()))
    startDay = datetime (now.year, now.month,now.day, kDAYSTARTHOUR,0,0)
    if startDay > now: # it's still "yesterday" according to kDAYSTARTHOUR definition of when a day starts
        startDay = startDay + timedelta (hours=-24)
    startSecs =startDay.timestamp() # used to report time of an entry through the weighing tube
    nextDay = startDay + timedelta (hours=24)
    
    filename = kCAGE_PATH + kCAGE_NAME + '_' + str (startDay.year) + '_' + '{:02}'.format(startDay.month)+ '_' + '{:02}'.format (startDay.day)
    print ('opening file name = ' + filename)
    if saveData & kSAVE_DATA_LOCAL:
        outFile=open (filename, 'ab')
        from One_day_method2 import get_day_weights
    """
    Weight data is written to the file as grams, in 32 bit floating point format. Each run of data is
    prefaced by metadata from a 32 bit floating point metaData array of size 2. The first point contains
    the last 6 digits of the RFID code, as a negative value to make it easy for analysis code to find the
    start of each run. The second point contains the time in seconds since the start of the day.
    Both data items have been selected to fit into a 32 bit float.
    """
    metaData = array ('f', [0,0])
    global tag #tag variable is global indicating that it is the same variable that is changed by TagReader callback
    tag = 0
    
    while True:
        try:
            """
            Loop with a brief sleep, waiting for a tag to be read
            or a new day to start, in which case a new data file is made
            """
            while tag==0:
                if datetime.fromtimestamp (int (time())) > nextDay:
                    if saveData & kSAVE_DATA_LOCAL:
                        outFile.close()
                        print ('save data date =', startDay.year, startDay.month, startDay.day)
                        get_day_weights (kCAGE_PATH, kCAGE_NAME, startDay.year, startDay.month, startDay.day, kCAGE_PATH, False, True)
                    startDay = nextDay
                    nextDay = startDay + timedelta (hours=24)
                    startSecs =startDay.timestamp()
                    filename = kCAGE_PATH + kCAGE_NAME + '_' + str (startDay.year) + '_' + '{:02}'.format(startDay.month)  + '_' + '{:02}'.format (startDay.day)
                    if saveData & kSAVE_DATA_LOCAL:
                        outFile=open (filename, 'ab')
                        print ('opening file name = ' + filename)
                else:
                    sleep (kTIMEOUTSECS)
            """
            A Tag has been read. Fill the metaData array and tell the C++ thread to start
            recording weights
            """
            thisTag = tag
            print ('mouse = ', thisTag)
            metaData [0]= -(thisTag%100000)
            metaData[1]=time()-startSecs
            scale.threadStart (scale.arraySize)
            nReads = scale.threadCheck()
            lastRead=0
            """
            Keep reading weights into the array until a new mouse is read by 
            the RFID reader, or the last read weight drops below 2 grams, or
            the array is full, then stop the thread print the metaData array
            and the read weights from the thread array to the file
            """
            while (tag == thisTag or (tag == 0 and scale.threadArray [nReads-1] > 2)) and nReads < scale.arraySize:
                if nReads > lastRead:
                    print (nReads, scale.threadArray [nReads-1])
                    lastRead = nReads
                nReads = scale.threadCheck()
            nReads = scale.threadStop()
            if saveData & kSAVE_DATA_LOCAL:
                metaData.tofile (outFile)
                scale.threadArray[0:nReads-1].tofile(outFile)
            if saveData & kSAVE_DATA_REMOTE:
                response = requests.post(kSERVER_URL, data={'filename': filename, 'array': str ((metaData + scale.threadArray[0:nReads-1]).tobytes(), 'latin_1')}).text
                if response != '\nSuccess\n':
                    print (reponse)
        except KeyboardInterrupt:
            while True:
                print ('---------------------------------------------------------------------------------------------------')
                event = int (input ('0 to tare\n1 to weigh once\n2 for avg of 10 readings\n3 to turn OFF\n4 to turn ON\n5 for threaded read\n6 to continue weighing\n7 to quit program\n:'))
                if event == 0:
                    scale.tare(5,True)
                elif event ==1:
                    print ('Weight =', scale.weighOnce(), 'g')
                elif event == 2:
                    print ('Weight =', scale.weigh(10), 'g')
                elif event == 3:
                    scale.turnOff()
                elif event == 4:
                    scale.turnOn()
                elif event == 5:
                    scale.threadStart (scale.arraySize)
                    nReads = scale.threadCheck() 
                    while nReads < scale.arraySize:
                        print ("Thread has read ", nReads, " weights, last reading was ", scale.threadArray [nReads-1])
                        nReads = scale.threadCheck()
                elif event == 6:
                    break
                elif event == 7:
                    if saveData & kSAVE_DATA_LOCAL:
                        outFile.close()
                    GPIO.cleanup()
                    return
        except Exception as error:
            print("Closing file...")
            outFile.close()
            raise error

if __name__ == '__main__':
   main()
