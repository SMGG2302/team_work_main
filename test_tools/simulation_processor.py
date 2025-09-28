import paho.mqtt.client as mqtt
import random
import threading
import time
import json


class  MainScreenSimulator:
    def __init__(self, broker="127.0.0.1", port=1883, username="", password="",
                 client_id=None, safe_topic="", control_topic_base="",shutdown_event=None, update_queue=None):
        self.broker=broker
        self.port=port      
        self.username=username
        self.password=password
        self.safe_topic=safe_topic
        self.control_topic_base=control_topic_base
        self.Flag_mqttConnected=0
        self.shutdown_event=shutdown_event
        self.update_queue=update_queue
        self.client_id=client_id

        #创建MQTT客户端
        self.is_connected=False   #连接状态
        self.heartbeat_value=0   #记录心跳值
        self.running = False   #运行标志
        self.control_signals={} #要发送的信号         

        #创建心跳线程和控制线程
        self.heartbeat_thread=None
        self.control_thread=None 
        


    '''初始化结束，下面是MQTT客户端的功能模块'''    
    #连接MQTT服务器
    def connect(self):
        try:
            self.client=mqtt.Client(client_id=self.client_id, clean_session=True)
            self.client.on_connect=self.on_connect                        #设置连接MQTT服务器的回调函数
            self.client.on_disconnect=self.on_disconnect                  #设置断开MQTT服务器的回调函数
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)   #添加用户名和密码
            
            result= self.client.connect(self.broker, self.port, 60) #连接MQTT
            
            if result != mqtt.MQTT_ERR_SUCCESS:
                 print(f"连接MQTT返回错误码: {result.name}({result.value})")
                 return False
            
            self.client.loop_start()          #启动MQTT客户端
            timeout = 10
            start_time = time.time()
            while not self.is_connected:
                time.sleep(0.1)
                if (time.time() - start_time) < timeout:
                    print("MQTT连接暂未超时，继续等待")  
        
            return self.is_connected         #返回连接状态

        except Exception as e:
            print(f"连接MQTT Broker时发生错误: {e}")
            return False
    
    # 连接的回调函数       
    def on_connect(self,client, userdata, flags, rc):
        if rc == 0:
            print("已连接到MQTT服务器")
            self.is_connected = True
        else:
            print(f"on_connect失败，错误代码：{rc}")
    
    # 断连的回调函数      
    def on_disconnect(self,client, userdata, rc):
        print("已断开与MQTT服务器的连接")
        self.is_connected = False
    
    '''以下开始是功能函数'''
    def start_send_signal(self):
        """启动发送控制信号和心跳"""
        self.running=True
        #启动心跳线程
        self.heartbeat_thread=threading.Thread(target=self.heartbeat_task,name="heartbeat_thread")
        self.heartbeat_thread.start()

        #启动控制线程
        self.control_thread=threading.Thread(target=self.control_task,name="control_thread")
        self.control_thread.start()

        print("已启动发送控制信号和心跳")
        return True
   
    #心跳发送功能函数
    def heartbeat_task(self):
        """心跳线程"""
        while self.running and not self.shutdown_event.is_set():
            if self.is_connected:  
                self.send_heartbeat()    
                print("已发送心跳") 
                time.sleep(0.1)     #每2秒发送一次心跳，修改数值可以修改发送速度

    def send_heartbeat(self):
        """发送心跳"""
        if not self.is_connected or not self.safe_topic:
           print(f"无法发送心跳,因为MQTT客户端未连接到服务器或缺少安全主题")
           return False
        try:
            self.heartbeat_value = (self.heartbeat_value + 1) % 256   #0-255循坏发送心跳
            
            #发布心跳消息
            result,_ = self.client.publish(
                self.safe_topic, 
                str(self.heartbeat_value), # json
                qos=0, 
                retain=False
            )
            if result == mqtt.MQTT_ERR_SUCCESS:
                print(f"已发送心跳: {self.heartbeat_value}")
            else:
                print(f"发送心跳失败: {result}")
                return False
        except Exception as e:
            print(f"发送心跳消息时发生错误: {e}")
            return False

    #控制信号发送功能函数
    def control_task(self):
        """控制线程"""
        send_count=0
        while self.running and not self.shutdown_event.is_set():
            if self.is_connected:  
                self.update_signal()
                self.send_control_signals()
                send_count+=1
                print(f"已发送{send_count}个控制信号")  
                time.sleep(0.1)    #每1秒发送一次控制信号


        #加载控制信号文件
    def update_signal(self):
        """手动控制信号"""
        try:
            self.control_signals.update({
                "action1":129,
                "action2":130,
                "action3":127,
                "action4":127,
                "action5":127,
                "action6":127,
                "power1":True,
                "power2":False,
                "power3":False,
                "power4":False,
                "power5":False,
                "power6":False,
                "power16":False,
                "power17":1080,
                "aux1":1,
                "aux2":0   
            })
        except Exception as e:
             print(f"加载信号文件失败: {e}")

    def send_control_signals(self):
        """发送控制信号"""
        if not self.is_connected or not self.control_topic_base:
            print("无法发送控制信号,因为MQTT客户端未连接到服务器或者没有控制主题基础")
            return False
        
        try:
            #发送控制信号
            success_conut=0
            for signal_name, signal_value in self.update_queue.items():
                topic=f"{self.control_topic_base}{signal_name}"
                payload=str(signal_value)                                  #话题实际内容
                result,_=self.client.publish(topic, payload, qos=0, retain=False)
                if result==mqtt.MQTT_ERR_SUCCESS:
                    print(f"已发送控制信号: {topic} - {payload}")
                    success_conut+=1
                else:
                    print(f"发送控制信号失败")
        except Exception as e:
            print(f"发送控制信号时发生错误: {e}")
            return False


    '''手动断连功能函数'''
    def disconnect(self):
        if self.client:
         self.client.loop_stop()
         self.client.disconnect()
         print("MQTT客户端已断开连接") 
    
    def stop_send_signal(self):
        """停止发送控制信号和心跳"""
        self.running=False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=1)      #join()函数等待线程结束，等待1s
        if self.control_thread:
            self.control_thread.join(timeout=1)
        print("已停止发送信号和心跳")

    
                         