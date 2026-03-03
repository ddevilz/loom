package com.example.payment.util;

import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

/**
 * Example class demonstrating Java reflection patterns
 */
public class ReflectionExample {
    
    public void loadClassDynamically(String className) throws Exception {
        // Class.forName pattern
        Class<?> clazz = Class.forName(className);
        Object instance = clazz.newInstance();
    }
    
    public void invokeMethodByName(Object obj, String methodName) throws Exception {
        // getMethod pattern with string literal
        Method method = obj.getClass().getMethod("processPayment");
        method.invoke(obj);
        
        // getDeclaredMethod pattern with variable
        Method dynamicMethod = obj.getClass().getDeclaredMethod(methodName);
        dynamicMethod.invoke(obj);
    }
    
    public Object createProxy(Class<?> interfaceClass) {
        // Proxy.newProxyInstance pattern
        return Proxy.newProxyInstance(
            interfaceClass.getClassLoader(),
            new Class<?>[] { interfaceClass },
            (proxy, method, args) -> {
                System.out.println("Method called: " + method.getName());
                return null;
            }
        );
    }
    
    public void getAllMethods(Class<?> clazz) {
        // getMethods pattern
        Method[] methods = clazz.getMethods();
        for (Method m : methods) {
            System.out.println(m.getName());
        }
    }
}
