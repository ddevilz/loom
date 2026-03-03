package com.example.payment.service;

import com.example.payment.domain.Payment;

public interface PaymentProcessor<T extends Payment> {
    void process(T payment);
    
    boolean canProcess(Payment payment);
    
    void refund(T payment);
}
