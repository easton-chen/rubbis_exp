CXXFLAGS=-g -std=c++0x -Wall -Werror -pedantic -Wno-vla
LDLIBS=-lboost_program_options -lboost_thread -lvirt -ltinyxml -lcurl -lboost_system -lstdc++

all: myactuator httpmon

httpmon: httpmon.cc

myactuator: assignCap.cpp
	g++ -o myactuator assignCap.cpp

clean:
	rm -f *.o myactuator httpmon

clear:
	rm -rf exp_2018*

delete:
	rm -f internal_data.txt external_data.txt
