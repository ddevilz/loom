package com.example.payment.repository;

import com.example.payment.domain.Payment;
import java.util.List;
import java.util.Optional;

public interface PaymentRepository {
    Payment save(Payment payment);
    
    Optional<Payment> findById(String id);
    
    List<Payment> findAll();
    
    void delete(String id);
}
