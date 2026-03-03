package com.example.payment.repository;

import com.example.payment.domain.Payment;
import org.springframework.stereotype.Repository;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

@Repository
public class InMemoryPaymentRepository implements PaymentRepository {
    private final Map<String, Payment> storage = new ConcurrentHashMap<>();

    @Override
    public Payment save(Payment payment) {
        storage.put(payment.getId(), payment);
        return payment;
    }

    @Override
    public Optional<Payment> findById(String id) {
        return Optional.ofNullable(storage.get(id));
    }

    @Override
    public List<Payment> findAll() {
        return new ArrayList<>(storage.values());
    }

    @Override
    public void delete(String id) {
        storage.remove(id);
    }
}
