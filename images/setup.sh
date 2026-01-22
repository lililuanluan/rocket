#!/bin/bash


if [ ! -d "./rippled" ]; then
	git clone git@github.com:XRPLF/rippled.git
fi

# 如果不存在cmake-3.25.1.tar.gz，则下载
if [ ! -f cmake-3.25.1.tar.gz ]; then
	wget https://github.com/Kitware/CMake/releases/download/v3.25.1/cmake-3.25.1.tar.gz
fi

if [ ! -f boost_1_75_0.tar.gz ]; then
	wget -O boost_1_75_0.tar.gz 'https://sourceforge.net/projects/boost/files/boost/1.75.0/boost_1_75_0.tar.gz/download'
fi



make build