
Classes 
1. BOARTIQInterface 
This is a plain Python class that runs on the host PC and communicates with the ARTIQ master process over a network connection. Acts as a bridge between ARTIQ and the BO: translating BO loop decisions into ARTIQ experiment submissions and then translating ARTIQ results back into Python data the BO loop can use.